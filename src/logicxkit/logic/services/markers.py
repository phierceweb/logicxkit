"""The marker track — `logic markers`; `markers_write` edits it. Measured on Logic's own five
marker edits of a blank-born project (2026-09-15, the `markers-a2*` goldens).

The track is the triple after the one whose events are type 0x11 (`arrangement.marker_sequence`);
its `qeSM` is a copy of the arrangement section sequence's, named for the Marker Set
(`Untitled`), and every blank-born project carries it empty. A marker is a 48-byte event of
type 0x12 like a section's: head tick; data +0 the slot of its `qSxT` name record, +8 zero,
+12 the length — 1 on every marker Logic made, shown as ∞ (to the next marker); a third `0x88`
line. Names are RTF text records (`Marker ##` numbers itself); a rename rewrites the RTF, a
move the head tick, a delete removes the event and its record.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from .arrangement import LENGTH_AT, SECTION_TYPE, TEXT_SLOT_AT, marker_sequence, text_records
from .events import Event, events
from .stream import HEADER, project_records
from .signature import Meter

TO_NEXT = 1                    # the length Logic writes: to the next marker


@dataclass(frozen=True)
class Marker:
    name: str
    tick: int                  # absolute, bar 1 at 38400
    length: int                # ticks; `TO_NEXT` runs to the next marker
    text_slot: int

    def bar(self, meter: Meter) -> float:
        return meter.bar(self.tick)


def _marker(e: Event, names: dict[int, str]) -> Marker:
    slot, length = (struct.unpack_from("<I", e.data, at)[0] for at in (TEXT_SLOT_AT, LENGTH_AT))
    return Marker(names.get(slot, ""), e.tick, length, slot)


def marker_number(data: bytes, text_slot: int) -> int:
    """The listing number the marker naming ``text_slot`` has now."""
    for n, m in enumerate(read_markers(data), 1):
        if m.text_slot == text_slot:
            return n
    raise ValueError(f"no marker names text record {text_slot} any more")


def read_markers(data: bytes) -> list[Marker]:
    """The markers in time order; empty without a marker track or markers."""
    records = project_records(data)
    t = marker_sequence(records)
    if t is None:
        return []
    names = text_records(records)
    found = [_marker(e, names) for e in events(records[t.end].raw[HEADER:]) if e.type == SECTION_TYPE]
    return sorted(found, key=lambda m: m.tick)
