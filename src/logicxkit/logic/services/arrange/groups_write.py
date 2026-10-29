"""Writers for Logic groups: a group made after the existing ones, a track assigned to one
group alone, a group renamed, its boxes set or switched on and off. Each rewrites the group's
triple and every member's bitmask through the record stream and validates the result; the
record format is `groups.py`'s."""

from __future__ import annotations

import json
import struct

from ..mixer.binding import bound_channels
from .environment import ENV_TAG, object_id_of
from .groups import (
    BEFORE_TAG, DEFAULT_FLAGS, EVENT_OBJECT_AT, EVENT_VALUE_AT, EVENT_VALUE_HI_AT, EVENT_VALUE_LO_AT, FADERS, FLAGS,
    GROUP_AT, GROUP_ON, ID_AT, NAME_AT, SLOT_STEP, TAIL, Group, _bit, _flags_at, _groups, _numbers, _object_groups,
    _DATA, _NAME_MAX, flags_for,
)
from ..stream.stream import HEADER, project_records, reassemble
from ..mixer.levels import FIXED_ONE, PAN_CENTRE, UNITY, read_levels
from .names import written
from ..stream.recbuild import fresh_uuid, rec, with_owner, with_slot
from ..stream.registry import GNOS_TAG, register_group
from ..stream.sequence import free_seq_id, sequences
from ..stream.validate import require_full_walk, require_valid


def _data() -> dict:
    from ....utils.data import data_file
    return json.loads(data_file("logic", _DATA).read_text())


def _with_name(payload: bytes, name: str) -> bytes:
    encoded = written(name, "a group name", limit=_NAME_MAX, empty=True)
    n = struct.unpack_from("<H", payload, NAME_AT)[0]
    padded = encoded + (b"\x00" if len(encoded) % 2 else b"")
    return payload[:NAME_AT] + struct.pack("<H", len(encoded)) + padded + payload[NAME_AT + 2 + n + (n & 1):]


def _with_flags(payload: bytes, flags: int) -> bytes:
    buf = bytearray(payload)
    struct.pack_into("<I", buf, _flags_at(payload), flags)
    return bytes(buf)


def _event(fader: str, object_id: int, value: int) -> bytes:
    e = bytearray(bytes.fromhex(_data()["member_events"][fader]))
    struct.pack_into("<I", e, EVENT_OBJECT_AT, object_id * 2)
    struct.pack_into("<I", e, EVENT_VALUE_AT, value)
    struct.pack_into("<H", e, EVENT_VALUE_HI_AT, value >> 16)
    struct.pack_into("<H", e, EVENT_VALUE_LO_AT, value & 0xFFFF)
    return bytes(e)


def member_events(flags: int, object_id: int, *, fader: int = UNITY * FIXED_ONE,
                  pan: int = PAN_CENTRE * FIXED_ONE) -> bytes:
    """The events ``flags`` give one member, carrying its ``fader`` (the channel's
    fixed-point word) and ``pan`` (the byte, shifted up)."""
    values = {"Volume": fader, "Pan": pan, "Mute": 0, "Solo": 0}
    return b"".join(_event(f, object_id, values[f]) for f in FADERS if flags >> FLAGS[f] & 1)


def _values(data: bytes) -> dict[int, dict[str, int]]:
    """object id -> the ``member_events`` keywords for its channel's fader and pan."""
    levels, owners = read_levels(data), bound_channels(data)
    out = {}
    for oid, owner in owners.items():
        if owner in levels:
            out[oid] = {"fader": levels[owner]["fader_fixed"], "pan": levels[owner]["pan"] * FIXED_ONE}
    return out


def _events_for(flags: int, members, values: dict[int, dict[str, int]]) -> bytes:
    return b"".join(member_events(flags, m, **values.get(m, {})) for m in members)


def _with_group(raw: bytes, mask: int) -> bytes:
    buf = bytearray(raw)
    struct.pack_into("<I", buf, HEADER + GROUP_AT, mask)
    return bytes(buf)


def _rebuild_events(raw: bytes, flags: int, members, values: dict[int, dict[str, int]]) -> bytes:
    events = raw[HEADER:]
    return rec(raw[:4], raw, _events_for(flags, members, values) + events[-TAIL:])


def _rewritten(data: bytes, groups: list[Group], changed: dict[int, tuple[bytes, bytes, tuple[int, ...]]],
               masks: dict[int, int]) -> bytes:
    """``changed``: group number -> (qeSM raw, qSvE raw, members); ``masks``: object id ->
    group mask for every object whose groups change."""
    records = project_records(data)
    by_start = {g.start: g for g in groups}
    out = []
    for i, r in enumerate(records):
        raw = r.raw
        g = by_start.get(i)
        if g is not None and g.number in changed:
            raw = changed[g.number][0]
        elif i - 2 in by_start and by_start[i - 2].number in changed:
            raw = changed[by_start[i - 2].number][1]
        else:
            oid = object_id_of(r)
            if oid in masks:
                raw = _with_group(raw, masks[oid])
        out.append(raw)
    return reassemble(data, out)


def _insert_at(records, groups: list[Group]) -> int:
    """Record index the new triple follows."""
    if groups:
        return max(g.start for g in groups) + 2
    heads = [i for i, r in enumerate(records) if r.tag == BEFORE_TAG]
    if heads:
        return heads[-1]
    first_env = next((i for i, r in enumerate(records) if r.tag == ENV_TAG), None)
    if first_env is None:
        raise ValueError("no place for a group triple: no rpyH or ivnE record")
    return first_env - 1


def create_group(data: bytes, *, name: str = "", members=(), settings=None,
                 flags: int | None = None) -> tuple[bytes, Group]:
    """A new group after the existing ones, holding ``members`` (object ids, in the order
    given) with ``settings`` (box names; the fresh-group defaults when None)."""
    require_full_walk(data)
    records = project_records(data)
    groups = _groups(records)
    flags = flags_for(settings) if settings is not None else (DEFAULT_FLAGS if flags is None else flags)
    number, slot = len(groups) + 1, len(groups) * SLOT_STEP
    seq_id = free_seq_id(sequences(records))
    d = _data()
    payload = _with_flags(_with_name(bytes.fromhex(d["qesm_payload"]), name), flags)
    qesm = bytearray(bytes.fromhex(d["qesm_header"]) + payload)
    struct.pack_into("<I", qesm, HEADER + ID_AT, seq_id)
    struct.pack_into("<I", qesm, 28, len(payload))
    qesm = with_slot(bytes(qesm), slot)
    marker = with_slot(bytes.fromhex(d["marker_header"]), slot)
    events = _events_for(flags, members, _values(data)) + bytes.fromhex(d["qsve_tail"])
    qsve = with_slot(with_owner(rec(b"qSvE", bytes.fromhex(d["qsve_header"]), events), seq_id), slot)
    objects = {object_id_of(r) for r in records} - {None}
    missing = [m for m in members if m not in objects]
    if missing:
        raise ValueError(f"no channel object {missing[0]}")
    old = _object_groups(records)
    out = []
    after = _insert_at(records, groups)
    uuid = fresh_uuid()
    for i, r in enumerate(records):
        raw = r.raw
        oid = object_id_of(r)
        if r.tag == GNOS_TAG:
            raw = rec(GNOS_TAG, raw, register_group(raw[HEADER:], slot=slot, uuid=uuid))
        elif oid in members:
            raw = _with_group(raw, old.get(oid, 0) | _bit(number))     # its other groups stay
        out.append(raw)
        if i == after:
            out += [qesm, marker, qsve]
    result = reassemble(data, out)
    require_valid(result)
    made = next(g for g in _groups(project_records(result)) if g.number == number)
    return result, made


def assign(data: bytes, object_id: int, number: int) -> bytes:
    """Put ``object_id``'s track in group ``number`` alone (0 = no group): its object's bit,
    an event per linked fader at the end of the group's list, and out of every other group."""
    require_full_walk(data)
    records = project_records(data)
    groups = _groups(records)
    by_number = {g.number: g for g in groups}
    if number and number not in by_number:
        raise ValueError(f"no group {number}; this project has {len(groups)}")
    if all(object_id_of(r) != object_id for r in records):
        raise ValueError(f"no channel object {object_id}")
    old = _object_groups(records).get(object_id, 0)
    if old == (_bit(number) if number else 0):
        return data
    changed, values = {}, _values(data)
    if number:
        g = by_number[number]
        members = tuple(m for m in g.members if m != object_id) + (object_id,)
        changed[number] = (records[g.start].raw, _rebuild_events(records[g.start + 2].raw, g.flags, members, values), members)
    for n in _numbers(old):
        if n != number and n in by_number:
            g = by_number[n]
            members = tuple(m for m in g.members if m != object_id)
            changed[n] = (records[g.start].raw, _rebuild_events(records[g.start + 2].raw, g.flags, members, values), members)
    result = _rewritten(data, groups, changed, {object_id: _bit(number) if number else 0})
    require_valid(result)
    return result


def set_group(data: bytes, number: int, *, name: str | None = None, settings=None,
              on: bool | None = None) -> bytes:
    """Rename group ``number``, set its boxes and/or switch it on or off; a changed fader
    set rewrites every member's events."""
    require_full_walk(data)
    records = project_records(data)
    groups = _groups(records)
    g = next((x for x in groups if x.number == number), None)
    if g is None:
        raise ValueError(f"no group {number}; this project has {len(groups)}")
    qesm = records[g.start].raw
    payload = qesm[HEADER:]
    flags = flags_for(settings, base=g.flags) if settings is not None else g.flags
    if on is not None:
        flags = (flags | GROUP_ON) if on else (flags & ~GROUP_ON)
    if name is not None:
        payload = _with_name(payload, name)
    payload = _with_flags(payload, flags)
    qsve = records[g.start + 2].raw
    if flags != g.flags:
        qsve = _rebuild_events(qsve, flags, g.members, _values(data))
    result = _rewritten(data, groups, {number: (rec(qesm[:4], qesm, payload), qsve, g.members)}, {})
    require_valid(result)
    return result
