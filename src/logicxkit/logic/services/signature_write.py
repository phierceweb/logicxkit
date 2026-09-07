"""Set the time signature at bar 1. Measured 2026-09-06 on Logic's own edit of a 5/4 song to
3/4: the first `0x30` event moved to the earliest bar line
before bar 1 (tick 38400 mod bar length), its head took the new numerator at +12 and the
denominator's log2 at +11, and its data line the bar index as i16 at +8 (negative, bar 1 = 0)
with bar 1's tick at +12. Bit 7 of head +15 marks the event Logic last edited and moves on
to the next edit, so it is left alone. Logic also re-snapped a later change to the next bar
line of the new meter, so a song with later changes is refused here.

Changes after bar 1, measured on Logic's own edits: a key change is a bare
0x32 event with the key number at head +12 and its own tick at data +12; a meter change is a
0x30 event with numerator and denominator in the head, the bar index at data +8, its tick at
data +12 and one empty continuation line. Logic wrote a session word at head +2 and data +10
of the key event, undecoded and written as zero here; the meter change's data +12 held a tick
one beat short of the event's in Logic's own file, so it is informational (the bar-1 events
and a converted song's change carry the event's own tick there, which is what is written).
"""

from __future__ import annotations

import struct

from .events import BAR_ONE, PPQ, events
from .insert import HEADER, project_records, reassemble
from .recbuild import rec
from .settings import set_key_root
from .signature import (
    BAR_INDEX_AT,
    DENOM_LOG2_AT,
    KEY_AT,
    KEY_TYPE,
    KeySignature,
    NUMERATOR_AT,
    TICK_AT,
    TIME_TYPE,
    key_number,
    signature_sequence,
)

_DENOMS = (1, 2, 4, 8, 16, 32)


def bar_one_event(numerator: int, denominator: int, template: bytes) -> tuple[bytes, list[bytes]]:
    """The head and lines of a bar-1 time signature, over an existing event's bytes."""
    if not 1 <= numerator <= 32 or denominator not in _DENOMS:
        raise ValueError(f"{numerator}/{denominator} is not a time signature Logic takes")
    bar = PPQ * 4 * numerator // denominator
    tick = BAR_ONE % bar
    head = bytearray(template[:16])
    struct.pack_into("<I", head, 4, tick)
    head[DENOM_LOG2_AT] = _DENOMS.index(denominator)
    head[NUMERATOR_AT] = numerator
    data = bytearray(template[16:32])
    struct.pack_into("<h", data, BAR_INDEX_AT, -((BAR_ONE - tick) // bar))
    struct.pack_into("<I", data, TICK_AT, BAR_ONE)
    return bytes(head), [bytes(data)] + [template[32 + 16 * k:48 + 16 * k] for k in range((len(template) - 32) // 16)]


def set_time_signature(data: bytes, numerator: int, denominator: int, *, force: bool = False) -> bytes:
    """The meter at bar 1; refused when the song changes meter later unless ``force``."""
    records = project_records(data)
    i = signature_sequence(records)
    if i is None:
        raise ValueError("the song has no signature track")
    payload = records[i].raw[HEADER:]
    evs = events(payload)
    times = [e for e in evs if e.type == TIME_TYPE]
    if not times:
        raise ValueError("the signature track has no time signature")
    if len(times) > 1 and not force:
        raise ValueError("the song changes meter later; Logic re-snaps those changes, so edit it there")
    first = times[0]
    raw = first.head + b"".join(first.lines)
    head, lines = bar_one_event(numerator, denominator, raw)
    body = sum(16 + 16 * len(e.lines) for e in evs)
    parts = [head + b"".join(lines) if e is first else e.head + b"".join(e.lines) for e in evs]
    out = [r.raw for r in records]
    out[i] = rec(records[i].tag, records[i].raw, b"".join(parts) + payload[body:])
    return reassemble(data, out)


def set_key(data: bytes, name: str) -> bytes:
    """The key signature at the start: the track's key event (7 + sharps, 0x10 for minor;
    measured on Logic's C -> G, A minor and E minor edits) and the song record's root, the
    key's own tonic."""
    number = key_number(name)
    records = project_records(data)
    i = signature_sequence(records)
    if i is None:
        raise ValueError("the song has no signature track")
    payload = records[i].raw[HEADER:]
    evs = events(payload)
    keys = [e for e in evs if e.type == KEY_TYPE]
    if len(keys) != 1:
        raise ValueError(f"the song has {len(keys)} key signature events; only a single one is edited here")
    first = keys[0]
    head = bytearray(first.head)
    head[KEY_AT] = number
    body = sum(16 + 16 * len(e.lines) for e in evs)
    parts = [bytes(head) + b"".join(e.lines) if e is first else e.head + b"".join(e.lines) for e in evs]
    out = [r.raw for r in records]
    out[i] = rec(records[i].tag, records[i].raw, b"".join(parts) + payload[body:])
    return set_key_root(reassemble(data, out), KeySignature(0, number).root)


def _events_with(data: bytes, new: bytes) -> bytes:
    records = project_records(data)
    i = signature_sequence(records)
    if i is None:
        raise ValueError("the song has no signature track")
    payload = records[i].raw[HEADER:]
    evs = events(payload)
    body = sum(16 + 16 * len(e.lines) for e in evs)
    kept = [e.head + b"".join(e.lines) for e in evs] + [new]
    kept.sort(key=lambda raw: struct.unpack_from("<I", raw, 4)[0])
    out = [r.raw for r in records]
    out[i] = rec(records[i].tag, records[i].raw, b"".join(kept) + payload[body:])
    return reassemble(data, out)


def _no_event_at(data: bytes, kind: int, tick: int) -> None:
    from .signature import read_signatures
    times, keys = read_signatures(data)
    have = [t.tick for t in times] if kind == TIME_TYPE else [k.tick for k in keys]
    if tick in have:
        raise ValueError(f"the signature track already has an event at tick {tick}")


def add_key_change(data: bytes, tick: int, name: str) -> bytes:
    """A key change to ``name`` at ``tick``."""
    number = key_number(name)
    if tick <= 0:
        raise ValueError("a key change needs a position after the start")
    _no_event_at(data, KEY_TYPE, tick)
    head = bytearray(16)
    struct.pack_into("<HHI", head, 0, KEY_TYPE, 0, tick)
    head[KEY_AT], head[15] = number, 1
    line = bytearray(16)
    line[7] = 0x88
    struct.pack_into("<I", line, TICK_AT, tick)
    return _events_with(data, bytes(head) + bytes(line))


def add_meter_change(data: bytes, tick: int, numerator: int, denominator: int) -> bytes:
    """A meter change to ``numerator``/``denominator`` at ``tick``, which must sit on a bar line."""
    from .signature import meter
    if not 1 <= numerator <= 32 or denominator not in _DENOMS:
        raise ValueError(f"{numerator}/{denominator} is not a time signature Logic takes")
    bar = meter(data).bar(tick)
    if tick <= BAR_ONE or bar != int(bar):
        raise ValueError(f"tick {tick} is not on a bar line after bar 1 (it is bar {bar:g})")
    _no_event_at(data, TIME_TYPE, tick)
    head = bytearray(16)
    struct.pack_into("<HHI", head, 0, TIME_TYPE, 0, tick)
    head[DENOM_LOG2_AT], head[NUMERATOR_AT], head[15] = _DENOMS.index(denominator), numerator, 1
    line = bytearray(16)
    line[0], line[7] = TIME_TYPE, 0x88
    struct.pack_into("<h", line, BAR_INDEX_AT, int(bar) - 1)
    struct.pack_into("<I", line, TICK_AT, tick)
    tail = bytearray(16)
    tail[7] = 0x88
    return _events_with(data, bytes(head) + bytes(line) + bytes(tail))
