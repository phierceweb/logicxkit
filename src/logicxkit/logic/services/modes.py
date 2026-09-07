"""Transport modes and the count-in — what the control bar shows lit — in the `gnoS` song
record. Measured 2026-09-08 on Logic 12.3.1 saves of one project, one press per save, as
payload offsets:

    +187  Replace      +188  Solo      +194  Cycle      +195  Autopunch     one byte, 1 = on
    +224  bit 0 Metronome Click — the same bit as the Metronome pane's "Click while playing"
          (the button also flips bit 2 of +2468, which Logic recomputes on load, so it is
          not written)
    +137  bit 4 Use Musical Grid (Record menu)
    +240  count-in length: 0 off, 1-6 that many bars, 7-15 one to nine beats (the Count In
          button turns 0 into 1)

The bytes up to +240 repeat 700 bytes on and Logic moved both copies on every press, so the
writer sets both; +137 has no copy. Logic clears Solo when it opens a project (a written 1
came back 0 on re-save, 2026-09-08), so ``copy_modes`` leaves it out. Software Monitoring,
Auto Input Monitoring, Pre Fader Metering, Low Latency Monitoring and Allow Quick Punch-In
left the project untouched — they are Logic's own settings (`prefs.py`). Skip Cycle is the
cycle locators swapped, not a flag.
"""

from __future__ import annotations

from .insert import HEADER, project_records
from .settings import MIRROR, _song, edit_song

MODES: dict[str, tuple[tuple[int, int, bool], ...]] = {   # name -> (payload offset, mask (0 = whole byte), mirrored)
    "Replace": ((187, 0, True),), "Solo": ((188, 0, True),), "Cycle": ((194, 0, True),), "Autopunch": ((195, 0, True),),
    "Metronome Click": ((224, 0x01, True),),
    "Use Musical Grid": ((137, 0x10, False),),
}
COUNT_IN_AT = 240
COUNT_INS = ("Off", "1 Bar", "2 Bars", "3 Bars", "4 Bars", "5 Bars", "6 Bars",
             "1/4", "2/4", "3/4", "4/4", "5/4", "6/4", "7/4", "8/4", "9/4")
COUNT_IN = "Count-in"
TRANSIENT = ("Solo",)          # read, but Logic drops it on load, so never copied


def _payload(data: bytes) -> bytes:
    records = project_records(data)
    return records[_song(records)].raw[HEADER:]


def read_modes(data: bytes) -> dict[str, bool | str]:
    """name -> on, plus ``Count-in`` -> its length as the Record menu names it."""
    g = _payload(data)
    out: dict[str, bool | str] = {}
    for name, places in MODES.items():
        at, mask, _mirrored = places[0]
        out[name] = bool(g[at] & mask) if mask else bool(g[at])
    n = g[COUNT_IN_AT]
    out[COUNT_IN] = COUNT_INS[n] if n < len(COUNT_INS) else f"code {n}"
    return out


def count_in_code(name: str) -> int:
    wanted = name.strip().lower()
    for i, item in enumerate(COUNT_INS):
        if item.lower() == wanted:
            return i
    raise ValueError(f"{name!r}: choose from {', '.join(COUNT_INS)}")


def _set(g: bytearray, at: int, mask: int, on, mirrored: bool = True) -> None:
    for a in ((at, at + MIRROR) if mirrored else (at,)):
        if a >= len(g):
            continue
        if mask:
            g[a] = (g[a] | mask) if on else (g[a] & ~mask & 0xFF)
        else:
            g[a] = int(on)


def set_modes(data: bytes, want: dict[str, bool | str]) -> bytes:
    """``want`` maps mode names to on/off and may carry ``Count-in`` -> a length name."""
    unknown = set(want) - set(MODES) - {COUNT_IN}
    if unknown:
        raise ValueError(f"unknown mode(s): {sorted(unknown)}; choose from {', '.join(MODES)} or {COUNT_IN}")

    def edit(g: bytearray) -> None:
        for name, value in want.items():
            if name == COUNT_IN:
                _set(g, COUNT_IN_AT, 0, count_in_code(str(value)))
            else:
                for at, mask, mirrored in MODES[name]:
                    _set(g, at, mask, bool(value), mirrored)

    return edit_song(data, edit)


def copy_modes(src: bytes, dst: bytes) -> tuple[bytes, dict[str, bool | str]]:
    """``dst`` with ``src``'s modes and count-in, Solo aside; the set copied."""
    want = {k: v for k, v in read_modes(src).items() if k not in TRANSIENT}
    return set_modes(dst, want), want


__all__ = ["COUNT_IN", "COUNT_INS", "MODES", "copy_modes", "count_in_code", "read_modes", "set_modes"]
