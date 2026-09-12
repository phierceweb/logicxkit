"""Read-only `.logicx` analysis: per-channel insert chains, AU preset names, native `GAMETSPP`
params and the track-name table, with project params from ``MetaData.plist``."""

from __future__ import annotations

import plistlib
import re
from pathlib import Path

from logicxkit.logicx import channel_blocks, channel_label, first_alternative

from .._binary import find_blocks, identify_plugin, read_block_floats
from .comp import decode_comp
from .eq import decode_eq
from .insert import HEADER, project_records
from .slots import is_plugin_slot

# Canonical plugin display names, most-specific needle first.
_PLUGINS = [
    ("Neutron 5 Transient Shaper", "Neutron"), ("Neutron 5", "Neutron 5"),
    ("Pro-Q 4", "Pro-Q 4"), ("Pro-C 2", "Pro-C 2"), ("Pro-MB", "Pro-MB"), ("Pro-L", "Pro-L"),
    ("smartGate", "smart:gate"), ("smartComp", "smart:comp"), ("InPhase", "InPhase"),
    ("Channel EQ", "Channel EQ"), ("ChanEQ", "Channel EQ"), ("Compressor", "Compressor"),
    ("Enveloper", "Enveloper"), ("Noise Gate", "Noise Gate"), ("Gain", "Gain"),
    ("SVT", "SVT"), ("Nectar", "Nectar 4"), ("Ozone", "Ozone 11"), ("Soldano", "Soldano"),
    ("Archetype", "Archetype"), ("Melodyne", "Melodyne"), ("EZbass", "EZbass"),
    ("Addictive", "Addictive Trigger"), ("Stealth", "Stealth"),
]

# channel-object version word: 06 = pre-2026 saves, 07 = Logic saves since 2026-06
# class version varies with the Logic build that saved the file — 5, 6 and 7 all occur.
# Pinning it to 6-7 makes `logic project` report 0 channels for older projects.
_SLOT_TAG = re.compile(rb".CuA")
_CST_REF = re.compile(rb"[ -~]{1,50}\.cst")
_PRESET = re.compile(rb"[ -~]{2,55}\.(?:aupreset|pst)")
_PLUGIN_TOKEN = re.compile(rb"[A-Za-z][ -~]{2,42}")
_TRACK_NAME = re.compile(rb"([ -~]{2,24}): \1\.(\d+)")
_SLOT_WINDOW = 260  # bytes after a .CuA tag to scan (proven on real songs)
_GENERIC_PRESETS = {"Untitled", "#default", "Default Setting"}


def _plugin_name(window: bytes) -> str | None:
    for m in _PLUGIN_TOKEN.finditer(window):
        s = m.group().decode("latin-1")
        for needle, disp in _PLUGINS:
            if needle in s:
                return disp
    return None


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
        name = _plugin_name(head)
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
        name = _plugin_name(window)
        if name is None:
            continue
        slot = (name, _preset_name(window))
        if not chain or chain[-1] != slot:  # drop spurious consecutive dupes
            chain.append(slot)
    return chain


def channel_natives(seg: bytes) -> list[tuple[str, dict]]:
    """Decoded native (Channel EQ / Compressor) GAMETSPP params in a channel."""
    out: list[tuple[str, dict]] = []
    for idx, _size, n in find_blocks(seg):
        plug = identify_plugin(seg, idx)
        if plug == "Compressor" and n >= 14:
            out.append((plug, decode_comp(read_block_floats(seg, idx, n))))
        elif plug == "Channel EQ" and n >= 33:
            out.append((plug, decode_eq(read_block_floats(seg, idx, n))))
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
    md = plistlib.loads((logicx / "Alternatives" / alt / "MetaData.plist").read_bytes())
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
