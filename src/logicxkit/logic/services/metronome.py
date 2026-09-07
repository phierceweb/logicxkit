"""The Metronome and Recording project settings — what File > Project Settings > Metronome
and > Recording show. Measured 2026-09-08 on Logic 12.3.1 saves of one project, one change
per save.

In the `gnoS` song record (payload offsets; only the +224 flags repeat 700 on in Logic's
own saves — the Recording bits, the pre-roll time and the Klopfgeist rows have a stale copy
there that Logic leaves alone, and so does the writer):

    +224  bit 0 Click while playing (the bar's Metronome button, `modes.py`), bit 1 set =
          Click while recording OFF, bit 3 Simple mode, bit 7 set = Polyphonic clicks OFF
    +223  bit 1 Automatically colorize takes          +227  bit 1 Automatically erase
          duplicates, bit 5 Allow tempo change recording, bit 6 set = MIDI data reduction OFF
    +284  1 = Pre-roll, 0 = Count-in (the Recording pane's radio)     +122  u32 pre-roll
          time, 10000 per second
    +516  four 32-byte Audio Click (Klopfgeist) rows — Bar, Beat, Group, Division — with the
          velocity at +11 and the note at +12 of each; the two bytes before them follow the
          velocity (0x80 0xff at 127) and are copied with the row

The MIDI click rows live in the Environment's click object: the one `ivnE` record of 414
bytes whose payload starts 0xe8 0x03. Four 48-byte rows from payload +180 — Bar, Beat,
Division, Group — each with the note-on status (0x90 + channel - 1) at +6, bit 7 of +13 set
when the row is OFF, the velocity at +17 and the note at +18. "Only during count-in" was
disabled while measuring and "Audio Click (Klopfgeist)" wrote nothing, so neither is here.
"""

from __future__ import annotations

import struct

from .insert import HEADER, project_records, reassemble
from .settings import MIRROR, edit_song

FLAGS_AT, TAKES_AT, RECORDING_AT, PREROLL_AT, PREROLL_TIME_AT = 224, 223, 227, 284, 122
KLOPFGEIST_AT, KLOPFGEIST_ROW, KLOPFGEIST_ROWS = 516, 32, ("Bar", "Beat", "Group", "Division")
CLICK_HEAD, CLICK_SIZE, CLICK_ROWS_AT, CLICK_ROW = b"\xe8\x03", 414, 180, 48
CLICK_ROWS = ("Bar", "Beat", "Division", "Group")
BITS: dict[str, tuple[int, int, bool]] = {          # name -> (payload offset, mask, set means off)
    "Click while playing": (FLAGS_AT, 0x01, False),
    "Click while recording": (FLAGS_AT, 0x02, True),
    "Simple mode": (FLAGS_AT, 0x08, False),
    "Polyphonic clicks": (FLAGS_AT, 0x80, True),
    "Automatically colorize takes": (TAKES_AT, 0x02, False),
    "Automatically erase duplicates": (RECORDING_AT, 0x02, False),
    "Allow tempo change recording": (RECORDING_AT, 0x20, False),
    "MIDI data reduction": (RECORDING_AT, 0x40, True),
    "Pre-roll instead of count-in": (PREROLL_AT, 0x01, False),
}
MIRRORED = {FLAGS_AT}
PREROLL = "Pre-roll seconds"


def _song(data: bytes) -> bytes:
    from .settings import _song as song_index
    records = project_records(data)
    return records[song_index(records)].raw[HEADER:]


def _click_index(records) -> int | None:
    hits = [i for i, r in enumerate(records)
            if r.tag == b"ivnE" and len(r.raw) == CLICK_SIZE and r.raw[HEADER:HEADER + 2] == CLICK_HEAD]
    return hits[0] if len(hits) == 1 else None


def read_metronome(data: bytes) -> dict:
    """The flags by name, the pre-roll time, the Klopfgeist rows and the MIDI click rows."""
    g = _song(data)
    out: dict = {name: (not bool(g[at] & mask)) if off else bool(g[at] & mask) for name, (at, mask, off) in BITS.items()}
    out[PREROLL] = struct.unpack_from("<I", g, PREROLL_TIME_AT)[0] / 10000
    out["Klopfgeist"] = {}
    for i, name in enumerate(KLOPFGEIST_ROWS):
        row = KLOPFGEIST_AT + i * KLOPFGEIST_ROW
        out["Klopfgeist"][name] = {"note": g[row + 12], "velocity": g[row + 11]}
    records = project_records(data)
    ci = _click_index(records)
    out["MIDI click"] = {}
    if ci is not None:
        c = records[ci].raw[HEADER:]
        for i, name in enumerate(CLICK_ROWS):
            row = CLICK_ROWS_AT + i * CLICK_ROW
            out["MIDI click"][name] = {"on": not bool(c[row + 13] & 0x80), "channel": (c[row + 6] & 0x0F) + 1,
                                      "note": c[row + 18], "velocity": c[row + 17]}
    return out


def set_metronome(data: bytes, want: dict) -> bytes:
    """``want`` maps the names in ``BITS`` to on/off and may carry ``Pre-roll seconds``."""
    unknown = set(want) - set(BITS) - {PREROLL}
    if unknown:
        raise ValueError(f"unknown setting(s): {sorted(unknown)}; choose from {', '.join(BITS)} or {PREROLL}")

    def edit(g: bytearray) -> None:
        for name, value in want.items():
            if name == PREROLL:
                struct.pack_into("<I", g, PREROLL_TIME_AT, round(float(value) * 10000))
                continue
            at, mask, off = BITS[name]
            stored = (not value) if off else bool(value)
            for a in ((at, at + MIRROR) if at in MIRRORED else (at,)):
                g[a] = (g[a] | mask) if stored else (g[a] & ~mask & 0xFF)

    return edit_song(data, edit)


def copy_metronome(src: bytes, dst: bytes) -> tuple[bytes, dict]:
    """``dst`` with ``src``'s flags, pre-roll, Klopfgeist rows and MIDI click rows."""
    s = _song(src)
    want = {name: (not bool(s[at] & mask)) if off else bool(s[at] & mask) for name, (at, mask, off) in BITS.items()}
    want[PREROLL] = struct.unpack_from("<I", s, PREROLL_TIME_AT)[0] / 10000
    out = set_metronome(dst, want)
    lo, hi = KLOPFGEIST_AT, KLOPFGEIST_AT + KLOPFGEIST_ROW * len(KLOPFGEIST_ROWS)

    def rows(g: bytearray) -> None:
        g[lo:hi] = s[lo:hi]

    out = edit_song(out, rows)
    src_records, records = project_records(src), project_records(out)
    si, di = _click_index(src_records), _click_index(records)
    if si is not None and di is not None:
        a, b = HEADER + CLICK_ROWS_AT, HEADER + CLICK_ROWS_AT + CLICK_ROW * len(CLICK_ROWS)
        raw = [r.raw for r in records]
        raw[di] = raw[di][:a] + src_records[si].raw[a:b] + raw[di][b:]
        out = reassemble(out, raw)
    return out, read_metronome(out)


__all__ = ["BITS", "CLICK_ROWS", "KLOPFGEIST_ROWS", "PREROLL", "copy_metronome", "read_metronome", "set_metronome"]
