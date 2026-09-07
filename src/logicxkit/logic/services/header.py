"""Track header components — which controls the arrange window's track headers show.

Not in ProjectData: the set lives in each alternative's `DisplayState.plist`, in the 312-byte
`ArrangeCLgUserData` blob under `screensetDictArray/layoutDictArray/docwWindowState/
udataArrange`, and again as the same blob inside `DisplayStateArchive`. Measured on seventeen
Logic 12.3.1 saves of one project, one component toggled per save (2026-09-04):

    +38   u16   header width in pixels = 109 + the widths of the shown components
    +58   u16   bit 3   Track Numbers HIDDEN
    +68   u16   bit 1 Volume, bit 2 Pan/Send, bit 3 On/Off, bit 4 Groove Track,
                bit 5 Track Alternatives — set = shown
    +70   u16   bit 0 Mute, bit 1 Record Enable, bit 2 Solo, bit 3 Track Icons,
                bit 5 Additional Name Column, bit 7 Input Monitoring, bit 8 Track Protect,
                bit 10 Freeze, bit 12 Color Bars — set = shown; bit 14 Control Surface Bars
                HIDDEN

Nothing else in the bundle moves with a toggle except the arrange scroll position.
"""

from __future__ import annotations

import plistlib
import struct
from pathlib import Path

BLOB_KEY = "ArrangeCLgUserData"
BLOB_LEN = 312
WIDTH_AT = 38
BASE_WIDTH = 109

# name -> (word offset, bit, set means shown, width when shown)
COMPONENTS: dict[str, tuple[int, int, bool, int]] = {
    "On/Off": (68, 3, True, 22),
    "Mute": (70, 0, True, 22),
    "Solo": (70, 2, True, 22),
    "Track Protect": (70, 8, True, 22),
    "Freeze": (70, 10, True, 22),
    "Record Enable": (70, 1, True, 26),
    "Input Monitoring": (70, 7, True, 22),
    "Volume": (68, 1, True, 128),
    "Pan/Send": (68, 2, True, 25),
    "Additional Name Column": (70, 5, True, 0),
    "Control Surface Bars": (70, 14, False, 5),
    "Track Numbers": (58, 3, False, 12),
    "Track Color Bars": (70, 12, True, 0),
    "Groove Track": (68, 4, True, 0),
    "Track Icons": (70, 3, True, 30),
    "Track Alternatives": (68, 5, True, 0),
}


def _find_blob(node):
    if isinstance(node, dict):
        for key, value in node.items():
            if key == BLOB_KEY and isinstance(value, bytes):
                return value
            found = _find_blob(value)
            if found is not None:
                return found
    elif isinstance(node, list):
        for value in node:
            found = _find_blob(value)
            if found is not None:
                return found
    return None


def _replace_blob(node, old: bytes, new: bytes) -> int:
    hits = 0
    if isinstance(node, dict):
        for key, value in list(node.items()):
            if isinstance(value, bytes) and value == old:
                node[key] = new
                hits += 1
            else:
                hits += _replace_blob(value, old, new)
    elif isinstance(node, list):
        for i, value in enumerate(node):
            if isinstance(value, bytes) and value == old:
                node[i] = new
                hits += 1
            else:
                hits += _replace_blob(value, old, new)
    return hits


def components_of(blob: bytes) -> dict[str, bool]:
    """name -> shown, read from the arrange blob."""
    if len(blob) != BLOB_LEN:
        raise ValueError(f"arrange blob is {len(blob)} bytes, expected {BLOB_LEN}")
    out = {}
    for name, (at, bit, set_means_shown, _w) in COMPONENTS.items():
        flag = bool(struct.unpack_from("<H", blob, at)[0] & (1 << bit))
        out[name] = flag if set_means_shown else not flag
    return out


def with_components(blob: bytes, shown: dict[str, bool]) -> bytes:
    """The blob with ``shown`` applied and the header width recomputed."""
    buf = bytearray(blob)
    state = components_of(blob)
    unknown = set(shown) - set(COMPONENTS)
    if unknown:
        raise ValueError(f"unknown component(s): {sorted(unknown)}; choose from {', '.join(COMPONENTS)}")
    state.update(shown)
    for name, (at, bit, set_means_shown, _w) in COMPONENTS.items():
        word = struct.unpack_from("<H", buf, at)[0]
        want_set = state[name] if set_means_shown else not state[name]
        word = word | (1 << bit) if want_set else word & ~(1 << bit) & 0xFFFF
        struct.pack_into("<H", buf, at, word)
    struct.pack_into("<H", buf, WIDTH_AT, header_width(state))
    return bytes(buf)


def header_width(state: dict[str, bool]) -> int:
    return BASE_WIDTH + sum(w for name, (_a, _b, _s, w) in COMPONENTS.items() if state.get(name))


def alternative_dirs(project: Path) -> list[Path]:
    return sorted(p for p in (project / "Alternatives").iterdir() if (p / "DisplayState.plist").exists())


def read_components(alternative: Path) -> dict[str, bool]:
    blob = _find_blob(plistlib.loads((alternative / "DisplayState.plist").read_bytes()))
    if blob is None:
        raise ValueError(f"{alternative}: no {BLOB_KEY} in DisplayState.plist")
    return components_of(blob)


def write_components(alternative: Path, shown: dict[str, bool]) -> dict[str, bool]:
    """Apply ``shown`` to one alternative's display state (both files) -> the resulting set."""
    from pf_core.utils.io import atomic_write_bytes

    state_path = alternative / "DisplayState.plist"
    state = plistlib.loads(state_path.read_bytes())
    old = _find_blob(state)
    if old is None:
        raise ValueError(f"{alternative}: no {BLOB_KEY} in DisplayState.plist")
    new = with_components(old, shown)
    if new == old:
        return components_of(old)
    _replace_blob(state, old, new)
    atomic_write_bytes(state_path, plistlib.dumps(state, fmt=plistlib.FMT_BINARY))
    archive_path = alternative / "DisplayStateArchive"
    if archive_path.exists():
        archive = plistlib.loads(archive_path.read_bytes())
        if _replace_blob(archive, old, new):
            atomic_write_bytes(archive_path, plistlib.dumps(archive, fmt=plistlib.FMT_BINARY))
    return components_of(new)
