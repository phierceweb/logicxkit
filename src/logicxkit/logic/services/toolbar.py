"""The toolbar — which buttons the row under the control bar shows.

Beside the control bar in each alternative's `DisplayState.plist`, under
`screensetDictArray/layoutDictArray/docwWindowState`, as `actionBarLayoutDict/CLgActionBarBtns`:
a list of button ids, mirrored in `DisplayStateArchive`. Ids measured 2026-09-07 on seven
Logic 12.3.1 saves of one project — every button on, the fourteen a template never shows,
and five subsets chosen by the bits of each button's index in Customize Toolbar's order.
Logic writes the list in the popover's reading order
(`ORDER`); the project's own default carried another order and loaded all the same. Logic
re-saved one of ours unchanged. Whether the row shows is `transportBarRows` beside it.
"""

from __future__ import annotations

import plistlib
from pathlib import Path

from .controlbar import _archive_holders, _archive_set, _names, alternative_dirs, window_states

LAYOUT_KEY, LIST_KEY = "actionBarLayoutDict", "CLgActionBarBtns"
ROWS_KEY = "transportBarRows"   # 1 = the control bar alone, 2 = with the toolbar row under it

# name -> id, in the order Logic writes them
BUTTONS: dict[str, int] = {
    "Bounce": 8, "Move to Track": 21, "Export": 13, "Move to Playhead": 29, "Import Audio": 7,
    "Nudge Value": 52, "Groups": 14, "Lock/Unlock SMPTE": 30, "Group Clutch": 44, "Repeat Section": 33,
    "Automation Quick Access": 40, "Cut Section": 34, "Learn": 36, "Insert Section": 35,
    "Articulation": 63, "Insert Silence": 22, "Track Zoom": 4, "Note Repeat": 61, "Shuffle": 58,
    "Spot Erase": 62, "Previous/Next Marker": 46, "Split by Playhead": 16, "Set Locators": 15,
    "Split by Locators": 17, "Zoom": 45, "Crop": 38, "Colors": 6, "Stretch to Locators": 20,
    "Remove Silence": 18, "Join": 19, "Bounce Regions": 39,
}
ORDER = list(BUTTONS.values())
NAMES = {v: k for k, v in BUTTONS.items()}


def buttons_of(ids: list[int]) -> dict[str, bool]:
    """name -> shown, for every known button; unknown ids are kept under their number."""
    have = set(ids)
    out = {name: (i in have) for name, i in BUTTONS.items()}
    for i in ids:
        if i not in NAMES:
            out[f"button {i}"] = True
    return out


def ids_for(want: dict[str, bool], current: list[int] | None = None) -> list[int]:
    """The list for ``want`` (name -> shown) over ``current``, in Logic's order."""
    have = set(current or [])
    for name, shown in want.items():
        i = BUTTONS[name]
        (have.add if shown else have.discard)(i)
    return [i for i in ORDER if i in have] + sorted(i for i in have if i not in NAMES)


def read_toolbar(alternative: Path) -> list[int]:
    state = plistlib.loads((alternative / "DisplayState.plist").read_bytes())
    for w in window_states(state):
        ids = w.get(LAYOUT_KEY, {}).get(LIST_KEY)
        if ids is not None:
            return [int(i) for i in ids]
    raise ValueError(f"{alternative}: no toolbar layout in DisplayState.plist")


def toolbar_shown(alternative: Path) -> bool:
    state = plistlib.loads((alternative / "DisplayState.plist").read_bytes())
    return any(int(w.get(ROWS_KEY, 1)) >= 2 for w in window_states(state))


def _edit(alternative: Path, plist_edit, archive_edit) -> None:
    """``plist_edit`` on every main window's state, ``archive_edit`` on the archive's objects."""
    from pf_core.utils.io import atomic_write_bytes

    state_path = alternative / "DisplayState.plist"
    state = plistlib.loads(state_path.read_bytes())
    windows = window_states(state)
    if not windows:
        raise ValueError(f"{alternative}: no window state in DisplayState.plist")
    for w in windows:
        plist_edit(w)
    atomic_write_bytes(state_path, plistlib.dumps(state, fmt=plistlib.FMT_BINARY))
    path = alternative / "DisplayStateArchive"
    if not path.exists():
        return
    archive = plistlib.loads(path.read_bytes())
    objs = archive.get("$objects")
    if isinstance(objs, list):
        archive_edit(objs)
        atomic_write_bytes(path, plistlib.dumps(archive, fmt=plistlib.FMT_BINARY))


def write_toolbar(alternative: Path, ids: list[int]) -> None:
    """The button list into every main window of the alternative, both display-state files."""
    def plist_edit(w):
        w.setdefault(LAYOUT_KEY, {})[LIST_KEY] = list(ids)

    def archive_edit(objs):
        for holder in _archive_holders(objs, LAYOUT_KEY):
            _archive_set(objs, holder, LIST_KEY, list(ids))

    _edit(alternative, plist_edit, archive_edit)


def show_toolbar(alternative: Path, shown: bool = True) -> None:
    rows = 2 if shown else 1

    def plist_edit(w):
        w[ROWS_KEY] = rows

    def archive_edit(objs):
        for o in objs:
            if isinstance(o, dict) and "NS.keys" in o and ROWS_KEY in _names(objs, o):
                _archive_set(objs, o, ROWS_KEY, rows)

    _edit(alternative, plist_edit, archive_edit)


def set_buttons(alternative: Path, want: dict[str, bool]) -> dict[str, bool]:
    ids = ids_for(want, read_toolbar(alternative))
    write_toolbar(alternative, ids)
    return buttons_of(ids)


def copy_toolbar(src: Path, dst: Path) -> dict[str, bool]:
    """The button set and whether the row shows, as in ``src``."""
    ids = read_toolbar(src)
    write_toolbar(dst, ids)
    show_toolbar(dst, toolbar_shown(src))
    return buttons_of(ids)


__all__ = ["BUTTONS", "ORDER", "alternative_dirs", "buttons_of", "copy_toolbar", "ids_for", "read_toolbar",
           "set_buttons", "show_toolbar", "toolbar_shown", "write_toolbar"]
