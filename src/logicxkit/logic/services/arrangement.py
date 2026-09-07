"""The Arrangement track — the song's sections (Intro, Verse, Chorus …). Read from the
files on hand (2026-09-06; twelve sections of one song reproduced against Logic's own
display); no writer yet.

A sequence triple near the head of the record stream whose `qSvE` events (`events.py`)
have type 0x12 and one data line:

    data +0   u32   slot of the section's text record        data +8    u32   kind
    data +12  u32   length, ticks                            (0 custom/intro, 1 verse,
                                                             2 chorus, 3 bridge, 4 outro)

Each section's name is a `qSxT` record carrying that slot in its header: plain,
NUL-terminated at +98, or an RTF document whose text is the name.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass

from .events import BAR_ONE, PPQ, Event, events
from .insert import HEADER, project_records
from .recbuild import slot_of
from .sequence import sequences

TEXT_TAG = b"qSxT"
TEXT_NAME_AT = 98
SECTION_TYPE = 0x12
TEXT_SLOT_AT, KIND_AT, LENGTH_AT = 0, 8, 12
KINDS = {0: "custom", 1: "verse", 2: "chorus", 3: "bridge", 4: "outro"}
_RTF_TEXT = re.compile(rb"\\cf\d+ ([^}\\]*)}\s*$")


@dataclass(frozen=True)
class Section:
    name: str
    start: int                 # ticks
    length: int                # ticks
    kind: int
    text_slot: int

    def bars(self, beats_per_bar: int = 4) -> tuple[float, float]:
        """(start bar, length in bars) for a constant meter; `signature.meter` handles changes."""
        bar = PPQ * beats_per_bar
        return ((self.start - BAR_ONE) / bar + 1, self.length / bar)


def _text(payload: bytes) -> str:
    raw = payload[TEXT_NAME_AT:].split(b"\0")[0]
    if raw.startswith(b"{\\rtf"):
        m = _RTF_TEXT.search(raw)
        return m.group(1).decode("latin-1").strip() if m else ""
    return raw.decode("latin-1")


def text_records(records) -> dict[int, str]:
    """slot -> the text of every `qSxT` record (section names, and other labels)."""
    return {slot_of(r.raw): _text(r.raw[HEADER:]) for r in records if r.tag == TEXT_TAG}


def _section(e: Event, names: dict[int, str]) -> Section:
    slot, kind, length = (struct.unpack_from("<I", e.data, at)[0] for at in (TEXT_SLOT_AT, KIND_AT, LENGTH_AT))
    return Section(names.get(slot, ""), e.tick, length, kind, slot)


def section_sequence(records) -> int | None:
    """Record index of the arrangement track's `qSvE`."""
    for t in sequences(records):
        p = records[t.end].raw[HEADER:]
        if len(p) >= 16 and struct.unpack_from("<I", p, 0)[0] == SECTION_TYPE:
            return t.end
    return None


def read_sections(data: bytes) -> list[Section]:
    """The arrangement's sections in time order; empty when the song has none."""
    records = project_records(data)
    i = section_sequence(records)
    if i is None:
        return []
    names = text_records(records)
    found = [_section(e, names) for e in events(records[i].raw[HEADER:]) if e.type == SECTION_TYPE]
    return sorted(found, key=lambda s: s.start)
