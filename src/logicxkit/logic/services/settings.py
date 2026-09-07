"""Project settings in the `gnoS` song record — the LCD's division and the key's root.
Measured 2026-09-06 on Logic's own edits of one song:

    +192  u8   division index: /16 = 7, /32 = 9, /48 = 10 (the popup's order, /4 = 4 … /192 = 14)
    +480  u32  ticks per division (240 for /16), a cache some files leave at 0
    +179  u8   key root, semitones above C (G = 7)

The block repeats 700 bytes on (+892, +1180, +879); Logic left the +1180 copy stale, so the
writers move both. The key's accidentals live on the signature track (`signature.py`).
"""

from __future__ import annotations

import struct

from .events import PPQ
from .insert import HEADER, project_records
from .registry import GNOS_TAG

DIVISION_AT, DIVISION_TICKS_AT, KEY_ROOT_AT = 192, 480, 179
MIRROR = 700
DIVISIONS = {4: 4, 8: 5, 12: 6, 16: 7, 24: 8, 32: 9, 48: 10, 64: 11, 96: 12, 128: 13, 192: 14}
MEASURED_DIVISIONS = (16, 32, 48)
NOTES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
_FLATS = {"Db": "C#", "Eb": "D#", "Gb": "F#", "Ab": "G#", "Bb": "A#", "Cb": "B", "Fb": "E"}


def _song(records) -> int:
    return next(i for i, r in enumerate(records) if r.tag == GNOS_TAG)


def read_settings(data: bytes) -> dict:
    """``division`` (the /N number, or the raw index when unmeasured), ``division_ticks``,
    ``key_root`` (a note name)."""
    g = project_records(data)[_song(project_records(data))].raw[HEADER:]
    index = g[DIVISION_AT]
    by_index = {v: k for k, v in DIVISIONS.items()}
    return {"division": by_index.get(index, index), "division_index": index,
            "division_ticks": struct.unpack_from("<I", g, DIVISION_TICKS_AT)[0],
            "key_root": NOTES[g[KEY_ROOT_AT] % 12]}


def root_semitone(name: str) -> int:
    n = name.strip().capitalize()
    n = _FLATS.get(n, n)
    if n not in NOTES:
        raise ValueError(f"{name!r} is not a note name")
    return NOTES.index(n)


def edit_song(data: bytes, edit) -> bytes:
    """``edit`` on a copy of the song record's payload; the project with it written back."""
    records = project_records(data)
    i = _song(records)
    g = bytearray(records[i].raw[HEADER:])
    edit(g)
    out = [r.raw for r in records]
    out[i] = records[i].raw[:HEADER] + bytes(g)
    from .insert import reassemble
    return reassemble(data, out)


_edit = edit_song


def set_division(data: bytes, division: int) -> bytes:
    """The LCD's division, /``division``."""
    if division not in DIVISIONS:
        raise ValueError(f"/{division} is not one of Logic's divisions: {sorted(DIVISIONS)}")
    index, ticks = DIVISIONS[division], PPQ * 4 // division

    def edit(g):
        for base in (0, MIRROR):
            g[DIVISION_AT + base] = index
            struct.pack_into("<I", g, DIVISION_TICKS_AT + base, ticks)
    return _edit(data, edit)


def set_key_root(data: bytes, name: str) -> bytes:
    """The key's root note in the song record (the signature track carries the accidentals)."""
    semitone = root_semitone(name)

    def edit(g):
        for base in (0, MIRROR):
            g[KEY_ROOT_AT + base] = semitone
    return _edit(data, edit)
