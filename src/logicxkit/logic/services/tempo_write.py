"""Set the project tempo — the bar-1 event and the `gnoS` words that held its value — and
add a tempo change. `--set 180` showed on Logic's LCD and survived its re-save (2026-09-06).
A change Logic added itself is one bare 32-byte event:
type 0x60, the tick, 0x7f at +12, the bpm word on the data line with `40 88` at +22 and an
ascending stamp at +8 — no curve lines; the word at head +2 it filled with is undecoded and
written as zero here. A ramp is what Logic's Tempo Operations "Create Tempo Curve" writes
(linear, density 1/8, continue with the new tempo): one such event per division from
the start bar to the end bar, each holding the tempo at the middle of its division, the last
one the end tempo exactly, no curve lines; Logic left every event selected (head +15 0x80).
"""

from __future__ import annotations

import struct

from .events import DATA_LINE, LINE, Event, events
from .insert import HEADER, project_records, reassemble
from .recbuild import rec
from .registry import GNOS_TAG
from .tempo import (
    BPM_AT,
    EVENT_TYPE,
    SCALE,
    TEMPO_ALT_AT,
    TEMPO_AT,
    TEMPO_THIRD_AT,
    tempo_sequence,
)

_MIN_BPM, _MAX_BPM = 5.0, 990.0


def set_tempo(data: bytes, bpm: float) -> bytes:
    """The tempo at bar 1 set to ``bpm``. Every project word that carried the old bar-1
    tempo follows (all three on a song without changes); later tempo events stay."""
    if not _MIN_BPM <= bpm <= _MAX_BPM:
        raise ValueError(f"{bpm} bpm is outside Logic's {_MIN_BPM:g}-{_MAX_BPM:g}")
    word = int(round(bpm * SCALE))
    records = project_records(data)
    i = tempo_sequence(records)
    if i is None:
        raise ValueError("the song has no tempo track")
    payload = records[i].raw[HEADER:]
    evs = events(payload)
    first = next(e for e in evs if e.type == EVENT_TYPE)
    old = struct.unpack_from("<I", first.data, BPM_AT)[0]
    body = sum(len(e.head) + LINE * len(e.lines) for e in evs)
    parts = []
    for e in evs:
        lines = list(e.lines)
        if e is first:
            ln = bytearray(e.data)
            struct.pack_into("<I", ln, BPM_AT, word)
            lines = [bytes(ln) if old_line[7] == DATA_LINE else old_line for old_line in lines]
        parts.append(e.head + b"".join(lines))
    out = [r.raw for r in records]
    out[i] = rec(records[i].tag, records[i].raw, b"".join(parts) + payload[body:])
    g = next(k for k, r in enumerate(records) if r.tag == GNOS_TAG)
    gp = bytearray(records[g].raw[HEADER:])
    for at in (TEMPO_AT, TEMPO_ALT_AT, TEMPO_THIRD_AT):
        if at + 4 <= len(gp) and struct.unpack_from("<I", gp, at)[0] == old:
            struct.pack_into("<I", gp, at, word)
    out[g] = records[g].raw[:HEADER] + bytes(gp)
    return reassemble(data, out)


STAMP_AT, STAMP_STEP = 8, 0x10000


def add_tempo(data: bytes, tick: int, bpm: float) -> bytes:
    """A tempo change to ``bpm`` at ``tick``, in tick order among the track's events."""
    if not _MIN_BPM <= bpm <= _MAX_BPM:
        raise ValueError(f"{bpm} bpm is outside Logic's {_MIN_BPM:g}-{_MAX_BPM:g}")
    if tick < 0:
        raise ValueError("a tempo change needs a position")
    records = project_records(data)
    i = tempo_sequence(records)
    if i is None:
        raise ValueError("the song has no tempo track")
    payload = records[i].raw[HEADER:]
    evs = events(payload)
    tempos = [e for e in evs if e.type == EVENT_TYPE]
    if not tempos:
        raise ValueError("the tempo track has no event to pattern the new one on")
    if any(e.tick == tick for e in tempos):
        raise ValueError(f"the track already has a tempo event at tick {tick}")
    body = sum(len(e.head) + LINE * len(e.lines) for e in evs)
    stamp = max(struct.unpack_from("<I", e.data, STAMP_AT)[0] for e in tempos) + STAMP_STEP
    new = _new_event(tempos[0], tick=tick, word=int(round(bpm * SCALE)), stamp=stamp)
    kept = [e.head + b"".join(e.lines) for e in evs] + [new]
    kept.sort(key=lambda raw: struct.unpack_from("<I", raw, 4)[0])
    out = [r.raw for r in records]
    out[i] = rec(records[i].tag, records[i].raw, b"".join(kept) + payload[body:])
    return reassemble(data, out)


def _new_event(pattern: Event, *, tick: int, word: int, stamp: int) -> bytes:
    head = bytearray(pattern.head)
    struct.pack_into("<HHI", head, 0, EVENT_TYPE, 0, tick)
    head[8:12] = bytes(4)
    head[15] = 1
    line = bytearray(pattern.data)
    struct.pack_into("<I", line, BPM_AT, word)
    line[6], line[7] = 0x40, DATA_LINE
    struct.pack_into("<I", line, STAMP_AT, stamp)
    line[12:] = bytes(4)
    return bytes(head) + bytes(line)


DIVISION_TICKS = {1: 3840, 2: 1920, 4: 960, 8: 480, 16: 240}


def ramp_events(start: int, bpm1: float, end: int, bpm2: float, per_bar: int = 8) -> list[tuple[int, float]]:
    """(tick, bpm) of a linear ramp as Logic's curve lays it out: every division from ``start``,
    the tempo at the division's midpoint, then ``bpm2`` at ``end``."""
    if per_bar not in DIVISION_TICKS:
        raise ValueError(f"density must be one of {sorted(DIVISION_TICKS)} per bar")
    step = DIVISION_TICKS[per_bar]
    if end <= start or (end - start) % step:
        raise ValueError("the ramp must end after it starts, a whole number of divisions later")
    n = (end - start) // step
    return [(start + k * step, bpm1 + (bpm2 - bpm1) * (k + 0.5) / n) for k in range(n)] + [(end, bpm2)]


def add_ramp(data: bytes, start: int, bpm1: float, end: int, bpm2: float, per_bar: int = 8) -> bytes:
    """A linear tempo ramp from ``bpm1`` at tick ``start`` to ``bpm2`` at tick ``end``. The
    track must carry no event inside the ramp."""
    for b in (bpm1, bpm2):
        if not _MIN_BPM <= b <= _MAX_BPM:
            raise ValueError(f"{b} bpm is outside Logic's {_MIN_BPM:g}-{_MAX_BPM:g}")
    records = project_records(data)
    i = tempo_sequence(records)
    if i is None:
        raise ValueError("the song has no tempo track")
    payload = records[i].raw[HEADER:]
    evs = events(payload)
    tempos = [e for e in evs if e.type == EVENT_TYPE]
    if not tempos:
        raise ValueError("the tempo track has no event to pattern the ramp on")
    inside = [e.tick for e in tempos if start <= e.tick <= end]
    if inside:
        raise ValueError(f"the track already has tempo events inside the ramp, at ticks {inside}")
    body = sum(len(e.head) + LINE * len(e.lines) for e in evs)
    stamp = max(struct.unpack_from("<I", e.data, STAMP_AT)[0] for e in tempos) + STAMP_STEP
    new = []
    for k, (tick, bpm) in enumerate(ramp_events(start, bpm1, end, bpm2, per_bar)):
        raw = _new_event(tempos[0], tick=tick, word=int(round(bpm * SCALE)), stamp=stamp + k * 0x200)
        new.append(raw[:15] + b"\x00" + raw[16:])                  # not marked as the last edit
    kept = [e.head + b"".join(e.lines) for e in evs] + new
    kept.sort(key=lambda raw: struct.unpack_from("<I", raw, 4)[0])
    out = [r.raw for r in records]
    out[i] = rec(records[i].tag, records[i].raw, b"".join(kept) + payload[body:])
    return reassemble(data, out)
