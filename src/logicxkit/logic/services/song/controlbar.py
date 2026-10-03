"""Control bar and display — which buttons and readouts the main window's control bar shows.

Not in ProjectData: each alternative's `DisplayState.plist` holds `transportLayoutDict` and
`udataTransport` under `screensetDictArray/layoutDictArray/docwWindowState` (one per window
and screenset), and `DisplayStateArchive` mirrors both as a keyed archive whose ints and
bools are one shared object per value — a write appends objects and repoints, never edits one. Measured on fifty Logic 12.3.1 saves of one project, one
control toggled per save (2026-09-04, the `controlbar-saves` golden, `cb-*`):
each section is a list of button ids that Logic keeps in one fixed order (`ORDER`,
read off the all-on saves), and a control that draws two buttons carries two ids.

    CLgTransportBtnsViewLeft / ViewRight   the Views column
    CLgTransportBtnsTransport              the Transport column
    CLgTransportBtnsDisplay                the Display column; 52 = the Left/Length radio
    CLgTransportBtnsModus                  Modes and Functions; 30 = the Master Volume box,
                                           53 with it = the popup on Output Meter
    udataTransport.DisplayMode             the LCD mode (`LCD_MODES`; the chevron menu and
                                           the popover's Display popup both set it)
    CLgTransportDisplayMode                the popover's copy of it, synced when it opens
    udataTransport.UseSMPTEViewOffset
"""

from __future__ import annotations

import plistlib
from pathlib import Path

LAYOUT_KEY, TRANSPORT_KEY = "transportLayoutDict", "udataTransport"
SECTIONS = ("CLgTransportBtnsViewLeft", "CLgTransportBtnsViewRight", "CLgTransportBtnsTransport",
            "CLgTransportBtnsDisplay", "CLgTransportBtnsModus")
_VL, _VR, _T, _D, _M = SECTIONS

# name -> the (section, id) pairs its box switches on, in the popover's order
CONTROLS: dict[str, tuple[tuple[str, int], ...]] = {
    "Library": ((_VL, 100),), "Inspector": ((_VL, 101),), "Quick Help": ((_VL, 102),),
    "Toolbar": ((_VL, 103),), "Smart Controls": ((_VL, 104),), "Mixer": ((_VL, 105),),
    "Editors": ((_VL, 106),), "List Editors": ((_VR, 107),), "Note Pad": ((_VR, 108),),
    "Apple Loops": ((_VR, 109),), "Browsers": ((_VR, 110),),
    "Go to Beginning": ((_T, 6),), "Go to Position": ((_T, 7),), "Go to Left Locator": ((_T, 8),),
    "Go to Right Locator": ((_T, 9),), "Go to Selection Start": ((_T, 10),),
    "Play from Beginning": ((_T, 1),), "Play from Left Window Edge": ((_T, 2),),
    "Play from Left Locator": ((_T, 3),), "Play from Right Locator": ((_T, 4),),
    "Play from Selection": ((_T, 5),), "Rewind/Fast Rewind": ((_T, 11),),
    "Forward/Fast Forward": ((_T, 12),), "Stop": ((_T, 13),), "Play": ((_T, 14),),
    "Pause": ((_T, 15),), "Record": ((_T, 16),), "Free Tempo Recording": ((_T, 50),),
    "Flashback Capture": ((_T, 17),), "Skip Cycle": ((_T, 35),), "Cycle": ((_T, 38),),
    "Positions (Time/Beats)": ((_D, 18),), "Locators or Punch Locators": ((_D, 19),),
    "Left/Length": ((_D, 52),), "Sample Rate / Buffer Size": ((_D, 20),),
    "Varispeed": ((_D, 46), (_M, 46)), "Tempo": ((_D, 21),),
    "Time Signature / Division": ((_D, 22),), "Key Signature / Project End": ((_D, 51),),
    "MIDI Activity (In/Out)": ((_D, 23),), "Performance Meter (CPU/HD)": ((_D, 24),),
    "Sync": ((_M, 44),), "Replace": ((_M, 42),), "Autopunch": ((_M, 39),),
    "Set Punch In/Out Locator by Playhead": ((_M, 40), (_M, 41)),
    "Software Monitoring": ((_M, 25),), "Auto Input Monitoring": ((_M, 26),),
    "Pre Fader Metering": ((_M, 28),), "Low Latency Monitoring Mode": ((_M, 29),),
    "Set Left/Right Locator by Playhead": ((_M, 31), (_M, 32)),
    "Set Left/Right Locator Numerically": ((_M, 33), (_M, 34)),
    "Move Locators by Cycle Length": ((_M, 36), (_M, 37)),
    "Tuner": ((_M, 47),), "Solo": ((_M, 43),), "Count In": ((_M, 48),),
    "Metronome Click": ((_M, 45),), "Master Volume": ((_M, 30),), "Output Meter": ((_M, 53),),
}
LCD_MODES = {0: "Custom", 1: "Time", 2: "Beats", 3: "Beats & Time (Large)",
             4: "Beats & Project (Large)", 7: "Beats & Project", 8: "Beats & Time"}

# each id's canonical rank: a newly ticked id goes after the last present id of lower rank,
# and a list otherwise keeps the order it was stored in (measured on both projects' saves)
ORDER: dict[str, tuple[int, ...]] = {
    _VL: (100, 101, 102, 103, 104, 105, 106),
    _VR: (107, 108, 109, 110),
    _T: (6, 7, 8, 9, 10, 1, 2, 3, 4, 5, 11, 12, 13, 14, 15, 16, 50, 17, 35, 38),
    _D: (18, 19, 21, 22, 24, 20, 46, 51, 23, 52),
    _M: (30, 53, 44, 42, 39, 40, 41, 25, 26, 28, 29, 31, 32, 33, 34, 36, 37, 46, 47, 43, 48, 45),
}


def window_states(state: dict) -> list[dict]:
    """Every `docwWindowState` in the plist that carries a control bar layout."""
    out = []
    for screenset in state.get("screensetDictArray", []):
        for layout in screenset.get("layoutDictArray", []):
            w = layout.get("docwWindowState")
            if isinstance(w, dict) and LAYOUT_KEY in w:
                out.append(w)
    return out


def controls_of(layout: dict) -> dict[str, bool]:
    """name -> shown, from one `transportLayoutDict`."""
    have = {s: set(layout.get(s, [])) for s in SECTIONS}
    return {name: all(i in have[s] for s, i in ids) for name, ids in CONTROLS.items()}


def _inserted(section: str, ids: list[int], new_id: int) -> list[int]:
    """``ids`` with ``new_id`` placed where Logic places it: after the last present id of
    lower canonical rank, at the front when there is none, at the end when it has no rank."""
    if new_id in ids:
        return ids
    rank = {v: k for k, v in enumerate(ORDER[section])}
    if new_id not in rank:
        return ids + [new_id]
    at = 0
    for pos, present in enumerate(ids):
        if present in rank and rank[present] < rank[new_id]:
            at = pos + 1
    return ids[:at] + [new_id] + ids[at:]


def with_controls(layout: dict, want: dict[str, bool]) -> dict:
    """``layout`` with the named controls switched on or off; every list keeps its stored
    order and a switched-on id is inserted where Logic inserts it."""
    new = {k: (list(v) if isinstance(v, list) else v) for k, v in layout.items()}
    for s in SECTIONS:
        new.setdefault(s, [])
    for name, on in want.items():
        for s, i in CONTROLS[name]:
            if on:
                new[s] = _inserted(s, new[s], i)
            elif i in new[s]:
                new[s] = [x for x in new[s] if x != i]
    return new


def alternative_dirs(project: Path) -> list[Path]:
    return sorted(p for p in (project / "Alternatives").iterdir() if (p / "DisplayState.plist").exists())


def read_layout(alternative: Path) -> tuple[dict, dict]:
    """``(transportLayoutDict, udataTransport)`` of the alternative's first main window."""
    state = plistlib.loads((alternative / "DisplayState.plist").read_bytes())
    windows = window_states(state)
    if not windows:
        raise ValueError(f"{alternative}: no control bar layout in DisplayState.plist")
    return dict(windows[0][LAYOUT_KEY]), dict(windows[0].get(TRANSPORT_KEY, {}))


def read_controls(alternative: Path) -> dict[str, bool]:
    return controls_of(read_layout(alternative)[0])


def _names(objs: list, holder: dict) -> list:
    return [objs[k.data] if isinstance(k, plistlib.UID) else k for k in holder["NS.keys"]]


def _archive_holders(objs: list, key: str) -> list[dict]:
    """The archived dictionaries stored under ``key`` of any archived dictionary — one per
    window for the layout and the LCD state."""
    out, seen = [], set()
    for o in objs:
        if isinstance(o, dict) and "NS.keys" in o:
            names = _names(objs, o)
            if key in names:
                ref = o["NS.objects"][names.index(key)]
                target = objs[ref.data] if isinstance(ref, plistlib.UID) else None
                if isinstance(target, dict) and "NS.keys" in target and id(target) not in seen:
                    seen.add(id(target))              # equal dictionaries are still separate windows
                    out.append(target)
    return out


def _archive_scalar(objs: list, value) -> plistlib.UID:
    """A reference to an archived int, bool or string equal to ``value`` — an existing one
    (the archiver keeps one object per value) or a new one appended; never a rewrite in
    place, since the object may back dozens of other keys."""
    for i, o in enumerate(objs):
        if type(o) is type(value) and o == value:
            return plistlib.UID(i)
    objs.append(value)
    return plistlib.UID(len(objs) - 1)


def _archive_set(objs: list, holder: dict, key: str, value) -> None:
    """Point ``key`` of the archived dictionary ``holder`` at ``value`` — a plain int/bool,
    or a list of ints as a fresh array shaped like the one it replaces (or like any archived
    array when the key is new); a key the dictionary lacks is appended."""
    names = _names(objs, holder)
    if key not in names:
        holder["NS.keys"].append(_archive_scalar(objs, key))
        holder["NS.objects"].append(None)
        names.append(key)
    at = names.index(key)
    ref = holder["NS.objects"][at]
    if isinstance(value, list):
        old = objs[ref.data] if isinstance(ref, plistlib.UID) else None
        if not isinstance(old, dict) or "NS.objects" not in old:
            old = next((o for o in objs if isinstance(o, dict) and "NS.objects" in o and "NS.keys" not in o), None)
            if old is None:
                raise ValueError("DisplayStateArchive: no archived array to shape the new list on")
        array = {k: v for k, v in old.items() if k != "NS.objects"}
        array["NS.objects"] = [_archive_scalar(objs, int(i)) for i in value]
        objs.append(array)
        holder["NS.objects"][at] = plistlib.UID(len(objs) - 1)
    elif isinstance(ref, plistlib.UID) or ref is None:
        holder["NS.objects"][at] = _archive_scalar(objs, value)
    else:
        holder["NS.objects"][at] = value


def _write_archive(alternative: Path, layout: dict, transport: dict | None) -> bool:
    """Every archived layout dictionary and, when given, every archived LCD state — one of
    each per window — set to match the plist."""
    from pf_core.utils.io import atomic_write_bytes

    path = alternative / "DisplayStateArchive"
    if not path.exists():
        return False
    archive = plistlib.loads(path.read_bytes())
    objs = archive.get("$objects")
    if not isinstance(objs, list):
        return False
    holders = _archive_holders(objs, LAYOUT_KEY)
    if not holders:
        return False
    for holder in holders:
        for key, value in layout.items():
            _archive_set(objs, holder, key, value)
    if transport:
        for holder in _archive_holders(objs, TRANSPORT_KEY):
            for key, value in transport.items():
                _archive_set(objs, holder, key, value)
    atomic_write_bytes(path, plistlib.dumps(archive, fmt=plistlib.FMT_BINARY))
    return True


def write_layout(alternative: Path, layout: dict, transport: dict | None = None) -> None:
    """Replace the control bar layout (and the LCD state when given) in every main window of
    the alternative — both display-state files."""
    from pf_core.utils.io import atomic_write_bytes

    state_path = alternative / "DisplayState.plist"
    state = plistlib.loads(state_path.read_bytes())
    windows = window_states(state)
    if not windows:
        raise ValueError(f"{alternative}: no control bar layout in DisplayState.plist")
    for w in windows:
        w[LAYOUT_KEY] = {k: (list(v) if isinstance(v, list) else v) for k, v in layout.items()}
        if transport:
            w.setdefault(TRANSPORT_KEY, {}).update(transport)
    atomic_write_bytes(state_path, plistlib.dumps(state, fmt=plistlib.FMT_BINARY))
    _write_archive(alternative, layout, transport)


def write_controls(alternative: Path, want: dict[str, bool]) -> dict[str, bool]:
    """Switch the named controls on or off in the alternative -> the resulting set."""
    layout, _transport = read_layout(alternative)
    new = with_controls(layout, want)
    if new != layout:
        write_layout(alternative, new)
    return controls_of(new)


def copy_layout(src: Path, dst: Path) -> dict[str, bool]:
    """The source alternative's control bar and LCD state onto the destination's."""
    layout, transport = read_layout(src)
    write_layout(dst, layout, transport)
    return controls_of(layout)
