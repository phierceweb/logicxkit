"""Writing a track's automation lane: the 16-byte fader events Logic's own Event List creates,
into the track's ``*Automation`` folder, replacing what that lane held (head +15, the list's
selection state, is left clear). A lane is a fader id (Volume 7, Pan 10, Mute 9, Solo 3) and
whether it is the relative lane; a point is (tick, value 0-127[, fraction]) — Volume 90 and Pan 64
are unity, the relative lane's 64 is 0 dB, the fraction the sub-tick at head +2. Points go in
Logic's own order: (tick, fraction, type, fader, relative). A copied lane keeps its events whole,
continuation lines included.
"""

from __future__ import annotations

import struct

from .automation import (
    FADER_POINT,
    FOLDER_NAME,
    FRACTION_UNIT,
    PARAM_LAST,
    param_slot,
    QESM_OBJECT_AT,
    RELATIVE,
    VALUE_UNIT,
    is_fader_point,
    named,
)
from ..song.events import LINE, events
from ..arrange.groups import FADER_IDS
from ..stream.stream import HEADER, project_records, reassemble
from ..stream.recbuild import rec
from ..stream.sequence import sequences
from ..stream.validate import require_valid

VALUE_MAX = 127
MAX_TICK = 0x7FFFFFFF                # byte 7's top bit would read as a continuation line
MAX_FRACTION = FRACTION_UNIT - 1


def fader_event(tick: int, value: int, fader: int, relative: bool = False, fraction: int = 0) -> bytes:
    """One point as Logic's Event List writes it, unselected (head +15 clear)."""
    if not 0 <= value <= VALUE_MAX:
        raise ValueError(f"an automation value is 0 to {VALUE_MAX}, not {value}")
    if not 0 <= tick <= MAX_TICK:
        raise ValueError(f"a point's tick is 0 to {MAX_TICK}, not {tick}")
    if not 0 <= fraction <= MAX_FRACTION:
        raise ValueError(f"a point's sub-tick fraction is 0 to {MAX_FRACTION}, not {fraction}")
    if fader not in FADER_IDS.values():
        raise ValueError(f"fader {fader} is not one of {sorted(FADER_IDS.values())}")
    head = bytearray(LINE)
    struct.pack_into("<HHI", head, 0, FADER_POINT | (RELATIVE if relative else 0), fraction, tick)
    head[11], head[12] = value, fader
    return bytes(head)


def param_event(tick: int, value: float, index: int, fraction: int = 0, slot: int = 1) -> bytes:
    """One plug-in parameter point of insert ``slot`` (from 1; the type word is 0x50 + slot):
    the 0..1 value as a u32 over 2^31 at +8, the parameter index at +12."""
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"a parameter point is 0 to 1, not {value}")
    if not 0 <= index <= 255:
        raise ValueError(f"a parameter index is 0 to 255, not {index}")
    if not 1 <= slot <= PARAM_LAST - FADER_POINT:
        raise ValueError(f"an insert is 1 to {PARAM_LAST - FADER_POINT}, not {slot}")
    if not 0 <= tick <= MAX_TICK:
        raise ValueError(f"a point's tick is 0 to {MAX_TICK}, not {tick}")
    head = bytearray(LINE)
    struct.pack_into("<HHII", head, 0, FADER_POINT + slot, fraction, tick, min(int(round(value * VALUE_UNIT)), VALUE_UNIT - 1))
    head[12] = index
    return bytes(head)


def _folder_record(records, track_object: int) -> int:
    for t in sequences(records):
        q = records[t.start].raw[HEADER:]
        if named(q, FOLDER_NAME) and struct.unpack_from("<I", q, QESM_OBJECT_AT)[0] == track_object:
            return t.end
    raise ValueError(f"track object {track_object} has no automation folder — Logic makes one when "
                     "the track is created; a track this tool added has none yet")


def _is_lane(e, fader: int, relative: bool) -> bool:
    return is_fader_point(e) and e.head[12] == fader and bool(e.type & RELATIVE) == relative


def _is_param_lane(e, index: int, slot: int) -> bool:
    return param_slot(e.type) == slot and e.head[12] == index


def _order(raw: bytes) -> tuple:
    kind, fraction, tick = struct.unpack_from("<HHI", raw, 0)
    return tick, fraction, kind & 0xFF, raw[12], bool(kind & RELATIVE)


def _with_lane(records, i: int, fader: int, relative: bool, new: list[bytes]) -> bytes:
    """The folder's record with the lane's events replaced by ``new``, the rest kept in place."""
    payload = records[i].raw[HEADER:]
    evs = events(payload)
    body = sum(LINE + LINE * len(e.lines) for e in evs)
    kept = [e.head + b"".join(e.lines) for e in evs if not _is_lane(e, fader, relative)]
    merged = sorted(kept + new, key=_order)
    return rec(records[i].tag, records[i].raw, b"".join(merged) + payload[body:])


def set_lane(data: bytes, track_object: int, fader: int, points, *, relative: bool = False) -> bytes:
    """The lane's points replaced by ``points`` — (tick, value) or (tick, value, fraction) — every
    other lane of the folder kept; two points at one position are refused."""
    if fader not in FADER_IDS.values():
        raise ValueError(f"fader {fader} is not one of {sorted(FADER_IDS.values())}")
    spec = [(p[0], p[1], p[2] if len(p) > 2 else 0) for p in points]
    positions = [(t, f) for t, _v, f in spec]
    if len(set(positions)) < len(positions):
        dup = next(p for p in positions if positions.count(p) > 1)
        raise ValueError(f"two points at tick {dup[0]} (fraction {dup[1]}); a position holds one point")
    new = [fader_event(t, v, fader, relative, f) for t, v, f in sorted(spec, key=lambda p: (p[0], p[2]))]
    records = project_records(data)
    i = _folder_record(records, track_object)
    out = [r.raw for r in records]
    out[i] = _with_lane(records, i, fader, relative, new)
    result = reassemble(data, out)
    require_valid(result)
    return result


def set_param_lane(data: bytes, track_object: int, index: int, points, slot: int = 1) -> bytes:
    """A plug-in parameter lane's points (insert from 1, parameter index) replaced by ``points`` —
    (tick, value 0..1) or (tick, value, fraction) — every other lane of the folder kept."""
    spec = [(p[0], p[1], p[2] if len(p) > 2 else 0) for p in points]
    positions = [(t, f) for t, _v, f in spec]
    if len(set(positions)) < len(positions):
        dup = next(p for p in positions if positions.count(p) > 1)
        raise ValueError(f"two points at tick {dup[0]} (fraction {dup[1]}); a position holds one point")
    new = [param_event(t, v, index, f, slot) for t, v, f in sorted(spec, key=lambda p: (p[0], p[2]))]
    records = project_records(data)
    i = _folder_record(records, track_object)
    payload = records[i].raw[HEADER:]
    evs = events(payload)
    body = sum(LINE + LINE * len(e.lines) for e in evs)
    kept = [e.head + b"".join(e.lines) for e in evs if not _is_param_lane(e, index, slot)]
    out = [r.raw for r in records]
    out[i] = rec(records[i].tag, records[i].raw, b"".join(sorted(kept + new, key=_order)) + payload[body:])
    result = reassemble(data, out)
    require_valid(result)
    return result


def clear_lane(data: bytes, track_object: int, fader: int, *, relative: bool = False) -> bytes:
    return set_lane(data, track_object, fader, [], relative=relative)


def copy_lane(data: bytes, src_object: int, dst_object: int, fader: int, *,
              relative: bool = False) -> bytes:
    """The source track's lane onto the destination track, replacing the destination's; the
    events go over whole, so a sub-tick position or a continuation line survives."""
    records = project_records(data)
    src = _folder_record(records, src_object)
    taken = [e.head + b"".join(e.lines) for e in events(records[src].raw[HEADER:]) if _is_lane(e, fader, relative)]
    if not taken:
        raise ValueError(f"track object {src_object} holds no points on that lane")
    dst = _folder_record(records, dst_object)
    out = [r.raw for r in records]
    out[dst] = _with_lane(records, dst, fader, relative, taken)
    result = reassemble(data, out)
    require_valid(result)
    return result
