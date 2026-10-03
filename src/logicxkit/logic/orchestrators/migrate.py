"""Migrate a session onto a template's layout in one run: choose the pairing (a map file, or
propose-map's draft), name the output, list what is left to do by hand, and on request have
Logic re-save the result and compare the two row lists."""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ..services.mixer.pairing import format_map, parse_map_full, propose_map, row_key
from ..services.project.project import project_metadata
from ..services.arrange.stacks import read_tracks
from .apply_template import lineage_problem

PREFIX = "CLAUDE migrated - "
LOGIC_APP = Path("/Applications/Logic Pro.app")
DRIVER = Path(__file__).resolve().parents[4] / "tools" / "driver"
OPEN_WAIT = 40
SAVE_POLLS, SAVE_POLL = 36, 5
# Measured over the staged ours/Logic re-save pairs: Logic sets high bits of the arrange row's
# flag word on its own; hidden and on, the bits that mean something, are compared separately.
CHURN = ("flag",)

_DISMISS = """tell application "System Events" to tell process "Logic Pro"
  repeat with b in {"Skip All", "Continue"}
    repeat with w in windows
      try
        click button b of w
      end try
      try
        click button b of sheet 1 of w
      end try
    end repeat
  end repeat
end tell"""

_CLOSE = """tell application "System Events" to tell process "Logic Pro"
  if (count of windows) is 0 then return "no window"
  perform action "AXRaise" of window 1
  keystroke "w" using command down
  delay 2
  repeat with w in windows
    try
      click button "Don’t Save" of w
    end try
    try
      click button "Don’t Save" of sheet 1 of w
    end try
  end repeat
end tell"""


def output_name(project: Path) -> str:
    return f"{PREFIX}{project.stem}.logicx"


@dataclass(frozen=True)
class Pairing:
    forced: dict[str, str | None] | None
    excluded: set[str] | None
    source: str                    # "map", "proposal" or "object id"
    proposal: str | None           # propose-map's draft, whenever no map file was given
    problem: str | None            # why the two are not one lineage


def choose_pairing(template: bytes, session: bytes, *, template_count: int | None,
                   session_count: int | None, map_text: str | None = None) -> Pairing:
    """A map file pairs as ``apply-template --map``. Without one the template's own lineage pairs
    by object id, since a guess must not override an id that pairs; any other gets the draft."""
    def lineage() -> str | None:
        return lineage_problem(template, session, template_count=template_count, session_count=session_count)

    if map_text is not None:
        forced, excluded = parse_map_full(map_text)
        return Pairing(forced, excluded, "map", None, None if forced else lineage())
    t_rows = read_tracks(template, template_count)
    proposal = format_map(propose_map(t_rows, read_tracks(session, session_count)), t_rows)
    problem = lineage()
    if problem is None:
        return Pairing(None, None, "object id", proposal, None)
    forced, excluded = parse_map_full(proposal)
    return Pairing(forced, excluded, "proposal", proposal, problem)


@dataclass
class Outcome:
    """What one alternative of the output got."""
    alternative: str
    ops: list = field(default_factory=list)
    kept: list[dict] = field(default_factory=list)
    note: str = ""


def checklist(outcomes: list[Outcome], bundle: Path, *, verify: bool = False) -> list[str]:
    lines = []
    several = len(outcomes) > 1
    for o in outcomes:
        where = f"{o.alternative}: " if several else ""
        if o.note:
            lines.append(f"  {where}left as it was — {o.note}")
        lines += [f"  {where}{op.line()}" for op in o.ops if op.status in ("refused", "failed")]
        if o.kept:
            lines.append(f"  {where}session-only, left as they are: " + ", ".join(row_key(r) for r in o.kept))
    if not lines:
        lines.append("  nothing refused, no session-only rows")
    if verify:
        return lines
    return lines + [
        "",
        f"  [ ] open {bundle} in Logic Pro; press Skip All or Continue on any dialog",
        "  [ ] File > Save As under a new name beside it; never Save over it",
        "  [ ] compare the two: `logic stacks --tracks` on each for the rows, `logic recdiff` for the records",
    ]


def verify_problem(*, platform: str = sys.platform, app: Path = LOGIC_APP, driver: Path = DRIVER,
                   which: Callable[[str], str | None] = shutil.which) -> str | None:
    """Why ``--verify`` cannot run here, or None."""
    if platform != "darwin":
        return f"it drives Logic Pro through macOS accessibility; this is {platform}"
    if not app.is_dir():
        return f"Logic Pro is not installed at {app}"
    if not (driver / "saveas.applescript").is_file():
        return "it needs tools/driver from a logicxkit checkout; this install has none"
    if which("osascript") is None or which("open") is None:
        return "osascript or open is not on PATH"
    return None


def compare_rows(ours: list[dict], logic: list[dict]) -> list[str]:
    """Positional differences between two arrange lists; empty when they match."""
    lines = []
    if len(ours) != len(logic):
        lines.append(f"{len(ours)} row(s) in ours, {len(logic)} in Logic's save")
    for i, (a, b) in enumerate(zip(ours, logic, strict=False), 1):
        changed = [f"{f} {a[f]!r} -> {b.get(f)!r}" for f in a if f not in CHURN and a[f] != b.get(f)]
        if changed:
            lines.append(f"row {i} {row_key(a)}: " + ", ".join(changed))
    lines += [f"row {i} {row_key(r)}: only in ours" for i, r in enumerate(ours[len(logic):], len(logic) + 1)]
    lines += [f"row {i} {row_key(r)}: only in Logic's save" for i, r in enumerate(logic[len(ours):], len(ours) + 1)]
    return lines


def _rows(bundle: Path, alternative: str) -> list[dict]:
    data = (bundle / "Alternatives" / alternative / "ProjectData").read_bytes()
    return read_tracks(data, project_metadata(bundle, alternative).get("tracks"))


@dataclass
class Verdict:
    resave: Path | None = None
    compared: list[str] = field(default_factory=list)
    differences: dict[str, list[str]] = field(default_factory=dict)
    only_ours: list[str] = field(default_factory=list)
    only_logic: list[str] = field(default_factory=list)
    problem: str | None = None

    @property
    def matched(self) -> bool:
        return self.problem is None and bool(self.compared) and not any(self.differences.values())


def compare_bundles(ours: Path, logic: Path) -> Verdict:
    """Row lists of the alternatives both bundles hold, paired by alternative folder name."""
    def alts(b):
        return {p.parent.name for p in b.glob("Alternatives/*/ProjectData")}
    a, b = alts(ours), alts(logic)
    both = sorted(a & b)
    return Verdict(resave=logic, compared=both, only_ours=sorted(a - b), only_logic=sorted(b - a),
                   differences={alt: compare_rows(_rows(ours, alt), _rows(logic, alt)) for alt in both})


def _run(argv: list[str]) -> tuple[int, str]:
    r = subprocess.run(argv, capture_output=True, text=True, timeout=300)
    return r.returncode, (r.stdout if r.returncode == 0 else r.stderr or r.stdout).strip()


def _resave(out_dir: Path, name: str) -> Path | None:
    for candidate in (out_dir / f"{name}.logicx", out_dir / name / f"{name}.logicx"):
        if any(candidate.glob("Alternatives/*/ProjectData")):
            return candidate
    return None


def verify(bundle: Path, out_dir: Path, *, run: Callable[[list[str]], tuple[int, str]] | None = None,
           sleep: Callable[[float], None] | None = None, driver: Path = DRIVER) -> Verdict:
    """Open ``bundle`` in Logic, Save As ``<stem> (Logic save)`` into ``out_dir`` through the
    driver, close it, and compare the row lists."""
    run, sleep = run or _run, sleep or time.sleep
    name = f"{bundle.stem} (Logic save)"
    if (out_dir / f"{name}.logicx").exists() or (out_dir / name).exists():
        return Verdict(problem=f"{out_dir / name} already exists; Logic's replace sheet would stop the driver")
    code, text = run(["open", "-a", "Logic Pro", str(bundle)])
    if code:
        return Verdict(problem=f"Logic Pro did not open the project: {text}")
    sleep(OPEN_WAIT)
    run(["osascript", "-e", _DISMISS])
    code, text = run(["osascript", str(driver / "saveas.applescript"), name, str(out_dir.resolve())])
    if code or text.startswith(("NO SAVE DIALOG", "NO DOCUMENT", "USAGE")):
        return Verdict(problem=f"Save As did not run ({text}); Logic is left as it is")
    resave, last = None, None
    for _ in range(SAVE_POLLS):
        found = _resave(out_dir, name)
        size = sum(p.stat().st_size for p in found.glob("Alternatives/*/ProjectData")) if found else None
        if found and size == last:
            resave = found
            break
        last = size
        sleep(SAVE_POLL)
    if resave is None:
        return Verdict(problem=f"no save named {name!r} appeared in {out_dir}; Logic is left as it is")
    run(["osascript", "-e", _CLOSE])
    return compare_bundles(bundle, resave)
