"""MIDI events inside a region's sequence, and the region's place on its track.

Measured 2026-09-13 on Logic 12.3.1's saves of a blank project (the public `midi-*` goldens).
A region is an 80-byte entry in the song container (`regions.py`): `+4` its start tick with
bar 1 at 34560 (the automation root folders sit there; a one-bar region the Event List placed
at 3 1 1 1 reads 42240), `+12` bit 0 Mute, `+13` bit 1 Loop (bit 0 marks the entry Logic last
edited, bit 2 every MIDI entry), `+28` the loop length in ticks or 0x3fffffff, `+32` its
sequence's slot. The sequence's `qeSM` carries the region name at `+16` (u16 byte length, UTF-8,
padded to even), the length 60 bytes past the padded name, the start in ticks from bar 1 at 224
and the loop flag (bit 1) at 76, and 4 bytes past the padded name the offset in ticks the
region plays its sequence from (a split's second piece keeps the parent's events and plays from
the cut; bit 7 of the byte 8 past the name set with it); its `qSvE` holds the events
(`events.py`), each tick relative to the sequence with 38400 at the region's start less that
offset:

    note            0x9c line: +11 velocity, +12 pitch; a 0x89 line follows, +12 u32 length
    controller      0xBc line: +11 value, +12 number; a 0xBB line follows
    program change  0xCc line: +12 program
    pitch bend      0xEc line: +12 LSB, +11 MSB

``c`` is the channel less one; `+15` bit 7 marks the selected event. Logic files them by
tick, and at one tick program change, controller, notes low to high, then pitch bend.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from .events import BAR_ONE, PPQ, Event, events
from .stream import HEADER, project_records
from .regions import ENTRY, placements, song_container
from .sequence import sequences, triple_by_slot
from .stacks import read_tracks
from .tracklist import arrange_run

REGION_BAR_ONE = 34560
ENTRY_TICK_AT, ENTRY_MUTE_AT, ENTRY_FLAGS_AT, ENTRY_LOOP_LENGTH_AT, ENTRY_SLOT_AT = 4, 12, 13, 28, 32
MUTE_BIT, LOOP_BIT, MIDI_BIT = 0x01, 0x02, 0x04         # +12 bit 0; +13 bits 1 and 2
NO_LOOP = 0x3FFFFFFF
MIDI_ENTRY = 0x20                   # entry type; 0x24 is an audio region
NAME_AT = 16
SEQ_OFFSET_AFTER_NAME, SEQ_OFFSET_FLAG_AFTER_NAME, SEQ_OFFSET_FLAG = 4, 8, 0x80
COLOUR_AFTER_NAME = 9
LENGTH_AFTER_NAME = 60
DATA1_AT, DATA2_AT = 12, 11
LENGTH_LINE, LENGTH_AT = 0x89, 12
KINDS = {0x90: "note", 0xB0: "controller", 0xC0: "program", 0xE0: "bend"}


@dataclass(frozen=True)
class MidiEvent:
    kind: str                  # note, controller, program, bend
    tick: int                  # absolute, bar 1 at 38400
    channel: int               # 1-16
    data1: int
    data2: int
    length: int = 0            # a note's, in ticks

    @property
    def pitch(self) -> int:
        return self.data1

    @property
    def velocity(self) -> int:
        return self.data2

    @property
    def number(self) -> int:
        return self.data1

    @property
    def program(self) -> int:
        return self.data1

    @property
    def value(self) -> int:
        """A controller's value, or a pitch bend's 14-bit one (8192 at centre)."""
        return (self.data2 << 7 | self.data1) if self.kind == "bend" else self.data2

    @property
    def bar(self) -> float:
        return (self.tick - BAR_ONE) / (PPQ * 4) + 1


@dataclass(frozen=True)
class MidiRegion:
    track: str
    row: int                   # 1-based arrange row
    name: str
    start: int                 # absolute tick, bar 1 at 38400
    loop: bool
    events: list[MidiEvent]
    slot: int | None = field(default=None, compare=False)      # its sequence triple's
    muted: bool = False
    at: int = field(default=-1, compare=False)                 # its entry's offset in the song container
    object_id: int = field(default=0, compare=False)           # the track object the entry names
    offset: int = field(default=0, compare=False)              # ticks into its sequence the region plays from
    length: int = field(default=0, compare=False)              # ticks; events outside [start, start + length) do not play
    colour: int = field(default=0, compare=False)              # a palette index, the ninth byte past the sequence's padded name

    @property
    def played(self) -> list[MidiEvent]:
        """The events inside the region's span — what Logic plays; a split leaves the rest in place."""
        return [e for e in self.events if self.start <= e.tick < self.start + self.length] if self.length else list(self.events)

    @property
    def start_bar(self) -> float:
        return (self.start - BAR_ONE) / (PPQ * 4) + 1


def _is_midi(e: Event) -> bool:
    return 0x80 <= (e.type & 0xFF) <= 0xEF


def _event(e: Event, start: int) -> MidiEvent:
    """``start``: the region's start less its sequence offset."""
    status = e.type & 0xFF
    length = 0
    if status & 0xF0 == 0x90:
        line = e.line(LENGTH_LINE)
        length = struct.unpack_from("<I", line, LENGTH_AT)[0] if line else 0
    return MidiEvent(KINDS.get(status & 0xF0, f"0x{status & 0xF0:02x}"), start + e.tick - BAR_ONE,
                     (status & 0x0F) + 1, e.head[DATA1_AT], e.head[DATA2_AT], length)


def name_end(qesm: bytes) -> int:
    """Offset in a `qeSM` record of the words after the padded region name."""
    n = struct.unpack_from("<H", qesm, HEADER + NAME_AT)[0]
    return HEADER + NAME_AT + 2 + n + (n & 1)


def sequence_offset(qesm: bytes) -> int:
    """Ticks into its sequence the region plays from (a split's second piece)."""
    return struct.unpack_from("<I", qesm, name_end(qesm) + SEQ_OFFSET_AFTER_NAME)[0]


def region_length(qesm: bytes) -> int:
    """A region's length in ticks, from its `qeSM` record."""
    return struct.unpack_from("<I", qesm, name_end(qesm) + LENGTH_AFTER_NAME)[0]


def _name(qesm: bytes) -> str:
    n = struct.unpack_from("<H", qesm, HEADER + NAME_AT)[0]
    return qesm[HEADER + NAME_AT + 2:HEADER + NAME_AT + 2 + n].decode("utf-8", "replace")


def entry_flags(entry: bytes) -> int:
    """Mute (`MUTE_BIT`) and Loop (`LOOP_BIT`) of an entry, as one word."""
    return (entry[ENTRY_MUTE_AT] & MUTE_BIT) | (entry[ENTRY_FLAGS_AT] & LOOP_BIT)


def read_midi(data: bytes, track_count: int | None = None) -> list[MidiRegion]:
    """Every region whose sequence holds only MIDI events (an empty region counts), in the
    song container's order."""
    records = project_records(data)
    run = arrange_run(records, track_count)
    song = song_container(records, run)
    if song is None:
        return []
    names = {r["object_id"]: r["name"] for r in read_tracks(data, track_count)}
    seqs = sequences(records)
    payload = records[song.end].raw[HEADER:]
    out = []
    for off, oid, row in placements(records, track_count):
        entry = payload[off:off + ENTRY]
        if struct.unpack_from("<H", entry, 0)[0] != MIDI_ENTRY:   # a flexed audio entry's +32 names its RBA sequence
            continue
        t = triple_by_slot(seqs, struct.unpack_from("<I", entry, ENTRY_SLOT_AT)[0])
        if t is None:
            continue
        evs = events(records[t.end].raw[HEADER:])
        if not all(_is_midi(e) for e in evs):
            continue
        start = struct.unpack_from("<I", entry, ENTRY_TICK_AT)[0] - REGION_BAR_ONE + BAR_ONE
        flags, offset = entry_flags(entry), sequence_offset(records[t.start].raw)
        out.append(MidiRegion(names.get(oid, f"object {oid}"), row, _name(records[t.start].raw), start,
                              bool(flags & LOOP_BIT), [_event(e, start - offset) for e in evs], t.slot, bool(flags & MUTE_BIT),
                              off, oid, offset, region_length(records[t.start].raw),
                              records[t.start].raw[name_end(records[t.start].raw) + COLOUR_AFTER_NAME]))
    return out
