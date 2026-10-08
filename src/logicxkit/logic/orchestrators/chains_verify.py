"""`chains --verify`: Logic's own Controls views as a second oracle for a written project.

`chains` checks what it wrote with the float decoder that wrote it; an offset wrong in both
directions passes. The independent read of one of Logic's own plug-ins is Logic's Controls view:
`tools/driver/controls.py` opens the written bundle, reads every slot's rows on the named tracks
and closes it without saving, and this module compares those rows with what the measured tables
(`plugin_params`) decode from the bundle's bytes. Nothing is written or staged.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ..services.mixer.plugin_params import decode_payload, load_tables, table_for
from ..services.mixer.plugins import slot_payloads
from ..services.mixer.slot_identity import slot_header
from ..services.mixer.slot_width import plugin_variant
from .migrate import DRIVER, LOGIC_APP

TOGGLES = {"off": "0", "on": "1"}            # a checkbox row shows 0/1 where a table names the choice
FILE_LABELS = {"Stereo Out": "Output 1-2"}   # the track header Logic shows -> the channel label the file carries
DRIVER_TOOLS = ("controls.py", "axdump.swift", "axact.swift", "click.swift")


def verify_problem(*, platform: str = sys.platform, app: Path = LOGIC_APP, driver: Path = DRIVER,
                   which: Callable[[str], str | None] = shutil.which) -> str | None:
    """Why ``--verify`` cannot run here, or None."""
    if platform != "darwin":
        return f"it drives Logic Pro through macOS accessibility; this is {platform}"
    if not app.is_dir():
        return f"Logic Pro is not installed at {app}"
    missing = [t for t in DRIVER_TOOLS if not (driver / t).is_file()]
    if missing:
        return f"it needs tools/driver from a logicxkit checkout ({', '.join(missing)} not found)"
    if which("osascript") is None or which("open") is None or which("swift") is None:
        return "osascript, open or swift is not on PATH"
    return None


def expected_rows(data: bytes, tracks: list[str]) -> dict[str, list[tuple[str, str, dict | None]]]:
    """Per track label, every audio slot in slot order: (plug-in name, the short name its header
    carries — what Logic's strip shows — and the parameters the tables decode from the bytes).
    One of Logic's own with no table gives {}; a third-party slot gives None."""
    tables = load_tables()
    out: dict[str, list[tuple[str, str, dict | None]]] = {t: [] for t in tracks}
    for ref, payload in slot_payloads(data):
        if ref.channel not in out or ref.midi:
            continue
        head = slot_header(payload)
        short = head.name if head else ""
        if not ref.native:
            out[ref.channel].append((ref.name, short, None))
            continue
        table = table_for(tables, head.code, plugin_variant(payload)) if head and isinstance(head.code, int) else None
        out[ref.channel].append((ref.name, short, decode_payload(table, payload) if table else {}))
    return out


def expected_units(data: bytes, tracks: list[str]) -> dict[str, dict[str, str]]:
    """Per track, each native slot's parameter units by name, for the display conversion."""
    tables = load_tables()
    out: dict[str, dict[str, str]] = {t: {} for t in tracks}
    for ref, payload in slot_payloads(data):
        if ref.channel not in out or not ref.native or ref.midi:
            continue
        head = slot_header(payload)
        table = table_for(tables, head.code, plugin_variant(payload)) if head and isinstance(head.code, int) else None
        if table:
            out[ref.channel].update({p.name: p.unit for p in table.params})
    return out


def channel_label(data: bytes, track: str) -> str:
    """The channel label a track's header name stands for: the channel bound to the arrange row
    of that name first (a renamed track: "Kick" on Audio 3; Logic's `addtrack-order-logic`, where
    the row headed "Audio 1" is bound to Audio 3), Output 1-2 for Stereo Out, else the name
    itself when a channel carries it."""
    from ..services.arrange.stacks import read_tracks
    for row in read_tracks(data, None):
        if row["name"] == track and row.get("label"):
            return row["label"]
    if track in FILE_LABELS:
        return FILE_LABELS[track]
    return track


def default_tracks(data: bytes, labels: set[str]) -> list[str]:
    """The header names the driver matches, for the channels labelled ``labels``: each bound
    arrange row's name in row order, Stereo Out for the output, else the label itself."""
    from ..services.arrange.stacks import read_tracks
    headers = {label: name for label, name in FILE_LABELS.items()}
    out, seen = [], set()
    for row in read_tracks(data, None):
        if row.get("label") in labels and row["label"] not in seen:
            out.append(row["name"])
            seen.add(row["label"])
    out += [headers.get(label, label) for label in sorted(labels - seen)]
    return out


def _squeeze(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.casefold())


_UNIT_SCALE = {"khz": 1000.0, "k": 1000.0, "s": 1000.0, "sec": 1000.0, "ms": 1.0, "hz": 1.0, "db": 1.0, "%": 1.0}


def _number(text: str, unit: str = "") -> tuple[float, float] | None:
    """(the number a display shows in the table's unit, half its last decimal place), or None.
    "1.2 kHz" against a Hz table is 1200 ± 50; "12 dB" is 12 ± 0.5; "1/8" is 0.125."""
    frac = re.match(r"^\s*(\d+)/(\d+)\b", text or "")
    if frac and int(frac.group(2)):
        return int(frac.group(1)) / int(frac.group(2)), 0.0
    m = re.match(r"^\s*([-+]?\d+(?:\.(\d+))?)\s*([A-Za-z%]*)", text or "")
    if not m:
        return None
    value, decimals, shown_unit = float(m.group(1)), len(m.group(2) or ""), m.group(3).lower()
    scale = 1.0
    if shown_unit in _UNIT_SCALE and unit.lower() in ("hz", "ms") and shown_unit not in (unit.lower(),):
        scale = _UNIT_SCALE[shown_unit] if shown_unit in ("khz", "k", "s", "sec") else 1.0
    return value * scale, 0.5 * 10 ** -decimals * scale


_BAND = re.compile(r"^band \d+ ", re.I)


def compare_slot(expected: dict, shown: list[dict], units: dict | None = None) -> tuple[list[str], int, list[str]]:
    """(the rows that differ, with both values; how many agree; the parameters the view did not
    show). A number agrees within half the display's last decimal place or 0.2 %, a kHz or s
    display read in the table's Hz or ms; a choice by its name, a checkbox by 0/1. A label the
    view repeats without its band (the Multipressor's four Response rows) pairs with the table's
    `Band N …` parameters in the order both list them; a label matched only loosely must be
    the one row that fits."""
    units = units or {}
    rows: dict[str, list[str]] = {}
    for row in shown:
        rows.setdefault(_squeeze(row.get("label", "")), []).append(row.get("display", ""))
    bare = {}                                      # a repeated label's rows, handed out in order
    for name in expected:
        stripped = _squeeze(_BAND.sub("", name))
        if _BAND.match(name) and len(rows.get(stripped, [])) > 1:
            bare.setdefault(stripped, []).append(name)
    taken = {k: iter(v) for k, v in rows.items() if k in bare and len(v) == len(bare[k])}
    differ, agreed, unread = [], 0, []
    for name, value in expected.items():
        key = _squeeze(name)
        stripped = _squeeze(_BAND.sub("", name))
        if stripped in taken:
            display = next(taken[stripped], None)
        else:
            display = rows.get(key, [None])[0]
        if display is None:
            loose = [d[0] for k, d in rows.items() if k and len(k) >= 4 and (key.endswith(k) or k.endswith(key))]
            display = loose[0] if len(loose) == 1 else None
        if display is None:
            unread.append(name)
            continue
        if isinstance(value, str):
            ok = _squeeze(display) in (_squeeze(value), TOGGLES.get(_squeeze(value)))
        else:
            n = _number(display, units.get(name, ""))
            ok = n is not None and abs(n[0] - float(value)) <= max(n[1], 0.0051, abs(n[0]) * 0.002)
        if ok:
            agreed += 1
        else:
            differ.append(f"{name}: file {value!r}, Logic shows {display!r}")
    return differ, agreed, unread


def _take_slot(slots: list[dict], short: str, name: str) -> dict | None:
    """The first driver slot labelled as the file's slot header is (`AdLimit`, `Multipr`: what
    Logic's strip shows), else as the plug-in is named, removed from the list."""
    for want in (_squeeze(short), _squeeze(name)):
        if not want:
            continue
        for i, slot in enumerate(slots):
            if _squeeze(slot.get("short", "")) == want:
                return slots.pop(i)
    return None


@dataclass
class Verdict:
    lines: list[str] = field(default_factory=list)        # one per slot: "track / plug-in: matched …" or the rows that differ
    differences: int = 0
    problem: str | None = None

    @property
    def matched(self) -> bool:
        return self.problem is None and bool(self.lines) and self.differences == 0


def _run(argv: list[str]) -> tuple[int, str]:
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=1800)
    except subprocess.TimeoutExpired:
        return 1, "the Controls reader did not finish in 30 minutes"
    return r.returncode, (r.stdout or r.stderr).strip()


def verify(bundle: Path, tracks: list[str], *, run: Callable[[list[str]], tuple[int, str]] | None = None,
           driver: Path = DRIVER) -> Verdict:
    """Read the named tracks' Controls views in Logic and compare them with the bundle's bytes.
    Logic opens a copy of the bundle in a scratch directory (it autosaves into what it opens),
    removed afterwards; the bundle itself is never opened."""
    run = run or _run
    alternative = sorted(bundle.glob("Alternatives/*/ProjectData"))
    if not alternative:
        return Verdict(problem=f"{bundle} holds no ProjectData")
    data = alternative[0].read_bytes()
    labels = {t: channel_label(data, t) for t in tracks}
    by_label = expected_rows(data, list(labels.values()))
    expected = {t: by_label[labels[t]] for t in tracks}
    units = expected_units(data, list(labels.values()))
    scratch = Path(tempfile.mkdtemp(prefix="logicxkit-verify-"))
    try:
        copy = scratch / bundle.name
        shutil.copytree(bundle, copy, ignore=shutil.ignore_patterns("Autosave*"))
        code, text = run([sys.executable, str(driver / "controls.py"), str(copy), *tracks])
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    try:
        read = json.loads(text[text.index("{"):]) if "{" in text else None
    except ValueError:
        read = None
    if read is None:
        return Verdict(problem=f"the Controls reader gave no report (exit {code}): {text[:300]}")
    verdict = Verdict()
    shown_by_track = {t["track"]: t for t in read.get("tracks", [])}
    for track in tracks:
        slots = list(shown_by_track.get(track, {}).get("slots", []))
        if not expected.get(track) and not slots:
            verdict.lines.append(f"{track}: no native slot in the file, none on Logic's strip")
            continue
        for name, short, values in expected.get(track, []):
            slot = _take_slot(slots, short, name)                      # the driver's slot of that name, in order
            if slot is None:
                verdict.lines.append(f"{track} / {name}: no slot of that name on Logic's strip")
                verdict.differences += 1
                continue
            if values is None:
                verdict.lines.append(f"{track} / {name}: third-party, not compared")
                continue
            if not values:
                verdict.lines.append(f"{track} / {name}: no table, not compared")
                verdict.differences += 1
                continue
            if not slot["rows"]:
                verdict.lines.append(f"{track} / {name}: Logic showed no Controls rows")
                verdict.differences += 1
                continue
            differ, agreed, unread = compare_slot(values, slot["rows"], units.get(labels[track], {}))
            verdict.differences += len(differ)
            tail = f" ({len(unread)} not shown)" if unread else ""
            if differ:
                verdict.lines.append(f"{track} / {name}: {len(differ)} differ, {agreed} agree{tail}: " + "; ".join(differ))
            elif agreed:
                verdict.lines.append(f"{track} / {name}: matched, {agreed} parameter(s){tail}")
            else:
                verdict.lines.append(f"{track} / {name}: nothing compared, {len(unread)} parameter(s) not shown")
                verdict.differences += 1
        for slot in slots:                                             # what Logic showed and nothing paired
            verdict.lines.append(f"{track} / {slot.get('short', '?')}: Logic shows it, not in the file's slots")
            verdict.differences += 1
    for problem in read.get("problems", []):
        verdict.lines.append(f"driver: {problem}")
        verdict.differences += 1
    return verdict
