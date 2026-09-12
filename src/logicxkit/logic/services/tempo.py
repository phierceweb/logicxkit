"""Tempo — the project tempo and the tempo track; `tempo_write` edits them.

`gnoS +110` is `bpm x 10000` as u32 — the tempo the LCD showed when the song was saved;
+114 is the tempo at bar 1 (equal unless the track has changes) and +198 repeats it. The
tempo track is the sequence triple near the head whose `qSvE` events (`events.py`) have
type 0x60:

    head +15  u8    flags — 0x40 marks a point Logic generated for a ramp
    data +0   u32   bpm x 10000                    data +8   u32   a stamp, ascending
    0xb4 line       curve parameters, undecoded    0xb1 line      zeros

A step is two events one tick apart; a ramp is a run of 0x40 points every 480 ticks.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from .events import Event, events
from .insert import HEADER, project_records
from .registry import GNOS_TAG
from .sequence import sequences

TEMPO_AT, TEMPO_ALT_AT, TEMPO_THIRD_AT = 110, 114, 198
SCALE = 10000
EVENT_TYPE = 0x60
FLAGS_AT, GENERATED = 15, 0x40
BPM_AT = 0
_MIN, _MAX = 5 * SCALE, 990 * SCALE


@dataclass(frozen=True)
class TempoEvent:
    position: int              # ticks
    bpm: float
    generated: bool            # a ramp point Logic made, not one the user placed


def project_tempo(data: bytes) -> tuple[float, float]:
    """(the LCD's tempo at save time, the tempo at bar 1) in bpm."""
    g = next(r.raw[HEADER:] for r in project_records(data) if r.tag == GNOS_TAG)
    return (struct.unpack_from("<I", g, TEMPO_AT)[0] / SCALE, struct.unpack_from("<I", g, TEMPO_ALT_AT)[0] / SCALE)


def _tempo(e: Event) -> TempoEvent:
    return TempoEvent(e.tick, struct.unpack_from("<I", e.data, BPM_AT)[0] / SCALE, bool(e.head[FLAGS_AT] & GENERATED))


def tempo_sequence(records) -> int | None:
    """Record index of the tempo track's `qSvE`."""
    for t in sequences(records):
        p = records[t.end].raw[HEADER:]
        if len(p) >= 32 and struct.unpack_from("<I", p, 0)[0] == EVENT_TYPE:
            bpm = struct.unpack_from("<I", p, 16 + BPM_AT)[0]
            if _MIN <= bpm <= _MAX:
                return t.end
    return None


def read_tempo_events(data: bytes) -> list[TempoEvent]:
    """The tempo track in file order, ramp points included."""
    records = project_records(data)
    i = tempo_sequence(records)
    if i is None:
        return []
    return [_tempo(e) for e in events(records[i].raw[HEADER:]) if e.type == EVENT_TYPE]
