"""Read-only `.logicx` analysis: per-channel insert chains, AU preset names, native `GAMETSPP`
params and the track-name table, with project params from ``MetaData.plist``."""

from __future__ import annotations

import plistlib
import re
from pathlib import Path

from logicxkit.logicx import channel_blocks, channel_label, first_alternative

from ..._binary import find_blocks, identify_plugin, read_block_floats
from ..mixer.comp import decode_comp
from ..mixer.eq import decode_eq
from ..mixer.slot_width import plugin_variant
from ..stream.stream import HEADER, project_records
from ..mixer.slots import is_plugin_slot
from ..mixer.plugin_names import NATIVE_INSTRUMENTS, native_name, plugin_name


# channel-object version word: 06 = pre-2026 saves, 07 = Logic saves since 2026-06
# class version varies with the Logic build that saved the file — 5, 6 and 7 all occur.
# Pinning it to 6-7 makes `logic project` report 0 channels for older projects.
_SLOT_TAG = re.compile(rb".CuA")
_CST_REF = re.compile(rb"[ -~]{1,50}\.cst")
_PRESET = re.compile(rb"[ -~]{2,55}\.(?:aupreset|pst)")
_TRACK_NAME = re.compile(rb"([ -~]{2,24}): \1\.(\d+)")
_SLOT_WINDOW = 260  # bytes after a .CuA tag to scan (proven on real songs)
_GENERIC_PRESETS = {"Untitled", "#default", "Default Setting"}


def _slot_name(payload: bytes) -> str | None:
    """The name string in the slot's window, else the native block's type id as `plugins`
    names it (a native slot need not carry a name string at all)."""
    name = plugin_name(payload[:_SLOT_WINDOW])
    if name is not None:
        return name
    from ..._binary import find_blocks
    blocks = find_blocks(payload)
    if not blocks or blocks[0][1] in NATIVE_INSTRUMENTS:
        return None
    type_id = blocks[0][1]
    return native_name(type_id, plugin_variant(payload)) or f"type {type_id}"


def _preset_name(window: bytes) -> str | None:
    m = _PRESET.search(window)
    if not m:
        return None
    name = m.group().decode("latin-1").rsplit(".", 1)[0]
    return None if name in _GENERIC_PRESETS else name


def channel_cst_refs(seg: bytes) -> list[str]:
    """``<name>.cst`` references in a channel block (which saved strip it loads)."""
    out: list[str] = []
    for m in _CST_REF.finditer(seg):
        name = m.group().decode("latin-1")
        if name not in out:
            out.append(name)
    return out


def strip_chain(data: bytes) -> list[tuple[str, str | None]]:
    """Insert chain of a `.cst` file, which is one channel object in the project's own format."""
    return channel_chain(data)


def channel_chain(seg: bytes) -> list[tuple[str, str | None]]:
    """Ordered (plugin, preset) inserts: the plugin-slot records of a segment that walks as records
    (a plugin name in a property record is not an insert), else the tag-window scan."""
    records = project_records(seg, start=0)
    if records and sum(len(r.raw) for r in records) == len(seg):
        return _chain_from_records(records)
    return _chain_from_windows(seg)


def _chain_from_records(records) -> list[tuple[str, str | None]]:
    slots = [r for r in records if r.tag == b"UCuA"]
    prop = min((r.key for r in slots if len(r.raw) - HEADER < 400 and b".cst" in r.raw), default=10)
    chain: list[tuple[str, str | None]] = []
    for r in slots:
        if not any(is_plugin_slot(r, prop, base) for base in (4, 3, 2)):
            continue
        head = r.raw[HEADER:HEADER + _SLOT_WINDOW]
        name = _slot_name(r.raw[HEADER:])
        if name is not None:
            chain.append((name, _preset_name(head)))
    return chain


def _chain_from_windows(seg: bytes) -> list[tuple[str, str | None]]:
    """Each slot bounded by the next ``.CuA`` tag (capped at ``_SLOT_WINDOW``) so a preset-less
    plugin can't borrow the next slot's preset."""
    tags = [m.start() for m in _SLOT_TAG.finditer(seg)]
    tags.append(len(seg))
    chain: list[tuple[str, str | None]] = []
    for i in range(len(tags) - 1):
        window = seg[tags[i]:min(tags[i + 1], tags[i] + _SLOT_WINDOW)]
        name = _slot_name(seg[tags[i]:tags[i + 1]])
        if name is None:
            continue
        slot = (name, _preset_name(window))
        if not chain or chain[-1] != slot:  # drop spurious consecutive dupes
            chain.append(slot)
    return chain


def channel_natives(seg: bytes) -> list[tuple[str, dict]]:
    """Decoded native GAMETSPP params in a channel: Channel EQ and Compressor by their own
    decoders, any other plug-in by its measured table (`plugin_params`)."""
    from ..mixer.plugin_params import decode, load_tables, table_for
    out: list[tuple[str, dict]] = []
    tables = load_tables()
    last: tuple | None = None                           # (record start, type, count) of the block before
    for idx, type_id, n in find_blocks(seg):
        record = seg.rfind(b"UCuA", 0, idx)
        if (record, type_id, n) == last:                # the copy a re-save writes after the live block
            continue
        last = (record, type_id, n)
        plug = identify_plugin(seg, idx)
        if plug == "Compressor" and n >= 14:
            out.append((plug, decode_comp(read_block_floats(seg, idx, n))))
        elif plug == "Channel EQ" and n >= 33:
            out.append((plug, decode_eq(read_block_floats(seg, idx, n))))
        else:
            start = seg.rfind(b"UCuA", 0, idx)             # the block's own slot record, for its variant
            table = table_for(tables, type_id, plugin_variant(seg[start + HEADER:idx]) if start >= 0 else None)
            if table is not None:
                out.append((table.name, decode(table, read_block_floats(seg, idx, n))))
    return out


def track_names(data: bytes) -> list[tuple[str, str]]:
    """The ``"Name: Name.N"`` track-name table, de-duplicated in file order."""
    out, seen = [], set()
    for m in _TRACK_NAME.finditer(data):
        nm = m.group(1).decode("latin-1")
        if nm not in seen:
            seen.add(nm)
            out.append((nm, m.group(2).decode()))
    return out


def analyze(project_data: bytes) -> dict:
    """Parse raw ``ProjectData`` bytes into channels + track names."""
    channels = []
    for a, b in channel_blocks(project_data):
        seg = project_data[a:b]
        if b - a < 40:
            continue
        chain = channel_chain(seg)
        refs = channel_cst_refs(seg)
        # a channel earns a row by embedding a chain OR referencing a saved strip —
        # clean-save templates (e.g. the Recording template) carry refs with no embedded state
        if not chain and not refs:
            continue
        entry = {"label": channel_label(seg), "chain": chain}
        if refs:
            entry["cst"] = refs
        natives = channel_natives(seg)
        if natives:
            entry["native"] = natives
        channels.append(entry)
    return {"channels": channels, "track_names": track_names(project_data)}


def project_metadata(logicx: Path, alt: str | None = None) -> dict:
    alt = alt or first_alternative(logicx)
    try:
        md = plistlib.loads((logicx / "Alternatives" / alt / "MetaData.plist").read_bytes())
    except FileNotFoundError:
        raise FileNotFoundError(f"{logicx}: Alternatives/{alt} has no MetaData.plist — not a Logic project") from None
    out = {
        "tracks": md.get("NumberOfTracks"),
        "bpm": md.get("BeatsPerMinute"),
        "key": md.get("SongKey"),
        "sig": f"{md.get('SongSignatureNumerator')}/{md.get('SongSignatureDenominator')}",
        "sample_rate": md.get("SampleRate"),
    }
    try:
        pi = plistlib.loads((logicx / "Resources/ProjectInformation.plist").read_bytes())
        out["logic_version"] = pi.get("LastSavedFrom")
    except (FileNotFoundError, OSError, ValueError):
        pass
    return out


def window_image_path(logicx: Path, alt: str | None = None) -> Path:
    """The auto-saved screenshot of whatever view was open at save; FileNotFoundError when absent."""
    logicx = Path(logicx)
    alt = alt or first_alternative(logicx)
    p = logicx / "Alternatives" / alt / "WindowImage.jpg"
    if not p.exists():
        raise FileNotFoundError(f"no WindowImage.jpg in {logicx.name}/Alternatives/{alt}")
    return p


def read_project(logicx: Path) -> dict:
    """Open a ``.logicx`` bundle and return its full inventory report."""
    logicx = Path(logicx)
    alt = first_alternative(logicx)
    data = (logicx / "Alternatives" / alt / "ProjectData").read_bytes()
    report = analyze(data)
    report["name"] = logicx.stem
    report["metadata"] = project_metadata(logicx, alt)
    return report
