"""Logic groups — the Mixer's Group slot. Measured on twenty-eight single-change saves
(Logic Pro 12.3.1, 2026-09-05: a group made, a second member, a second group, a rename, and
every box in Group Settings toggled one at a time).

A group is a sequence triple of its own — `qeSM` / zero-size `karT` / `qSvE` with header
`+6` = 0x11 — placed after the last `rpyH` record and before the first `ivnE`, one per
group in slot order (`+10` = 0, 4, 8 ...; group N sits in slot 4(N-1)). The `qeSM` payload:

    +8        u32   id, repeated as the `qSvE`'s owner; any unused triple id
    +16       u16   name length; the name follows, padded to an even length
    +70+name  u32   the settings, one bit per box (FLAGS); 0x81400005 on a fresh group

The `qSvE` holds one 32-byte event per member per linked fader — Volume, Mute, Solo and
Pan; every other box is flag-only — then a 16-byte tail. Event `+4` is the member's object
id doubled, `+12` the fader as Logic numbers them (7 Volume, 9 Mute, 3 Solo, 10 Pan), `+8`
the member's value for it as the channel stores it (the fader's fixed-point word; the pan
byte in the top byte), its halves repeated at `+20` and `+30`. A member's `ivnE` carries
the group number at `+24` (0 = none), and the registry holds a `<0x11><slot>` entry per
group in both runs, directly before the object entries. The row's `+4` and the channel's
`+92` do not change. Bit 31 of the flags is set on every group Logic 12.3.1 made and clear on
one older template group; its meaning is unmeasured, as is leaving a group (composed here:
the member's events go, its `+24` clears).
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass

from .binding import bound_channels
from .environment import ENV_TAG, object_id_of
from .insert import HEADER, project_records, reassemble
from .levels import FIXED_ONE, PAN_CENTRE, UNITY, read_levels
from .recbuild import fresh_uuid, rec, with_owner, with_slot
from .registry import GNOS_TAG, register_group
from .sequence import free_seq_id, is_group, sequences
from .validate import require_full_walk, require_valid

GROUP_AT = 24                       # ivnE: the member's group number, u32
ID_AT, NAME_AT = 8, 16
FLAGS_AFTER_NAME = 70
SLOT_STEP = 4
EVENT, TAIL = 32, 16
EVENT_OBJECT_AT, EVENT_FADER_AT, EVENT_VALUE_AT = 4, 12, 8
EVENT_VALUE_HI_AT, EVENT_VALUE_LO_AT = 20, 30
DEFAULT_FLAGS = 0x81400005
BEFORE_TAG = b"rpyH"                # the first group's triple follows the last of these
_NAME_MAX = 63
_DATA = "group-12.3.1.json"                # under the data root, `utils.data`

FLAGS = {
    "Volume": 0, "Pan": 1, "Mute": 2, "Solo": 3,
    **{f"Send {n}": 7 + n for n in range(1, 9)},
    "Editing (Selection)": 16, "Track Zoom": 17, "Color": 18, "Record": 20, "Hide": 21,
    "Quantize-Locked (Audio)": 22, "Track Alternatives": 23, "Automation Mode": 24, "Input": 26,
}
INVERTED = {"Quantize-Locked (Audio)"}          # the bit is set while the box is off
FADERS = ("Mute", "Volume", "Solo", "Pan")     # the boxes that give each member an event,
                                               # in the order Logic writes the pairs seen
FADER_IDS = {"Volume": 7, "Mute": 9, "Solo": 3, "Pan": 10}
_FADER_INDEX = {i: FADERS.index(n) for n, i in FADER_IDS.items()}
_KNOWN = sum(1 << b for b in FLAGS.values())


@dataclass(frozen=True)
class Group:
    number: int                     # 1-based; what a member's object carries
    slot: int
    group_id: int
    name: str
    flags: int
    members: tuple[int, ...]        # object ids, in event order then stream order
    start: int                      # record index of the qeSM

    @property
    def settings(self) -> list[str]:
        return settings_of(self.flags)

    @property
    def label(self) -> str:
        return self.name or f"Group {self.number}"


def settings_of(flags: int) -> list[str]:
    return [name for name, bit in FLAGS.items() if bool(flags >> bit & 1) != (name in INVERTED)]


def flags_for(settings, base: int = DEFAULT_FLAGS) -> int:
    """``base`` with every known box set from ``settings`` (names as Group Settings shows
    them); the unknown bits keep ``base``'s."""
    want = set()
    for s in settings:
        if s not in FLAGS:
            raise ValueError(f"{s!r} is not a group setting; choose from {', '.join(FLAGS)}")
        want.add(s)
    flags = base & ~_KNOWN
    for name, bit in FLAGS.items():
        if (name in want) != (name in INVERTED):
            flags |= 1 << bit
    return flags


def _data() -> dict:
    from ...utils.data import data_file
    return json.loads(data_file("logic", _DATA).read_text())


def _name_of(payload: bytes) -> str:
    n = struct.unpack_from("<H", payload, NAME_AT)[0]
    return payload[NAME_AT + 2:NAME_AT + 2 + n].decode("latin-1")


def _flags_at(payload: bytes) -> int:
    n = struct.unpack_from("<H", payload, NAME_AT)[0]
    return FLAGS_AFTER_NAME + n + (n & 1)


def _with_name(payload: bytes, name: str) -> bytes:
    if not name.isascii() or not name.isprintable() or len(name) > _NAME_MAX:
        raise ValueError(f"a group name is printable ASCII, at most {_NAME_MAX} characters")
    n = struct.unpack_from("<H", payload, NAME_AT)[0]
    encoded = name.encode("ascii")
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


def _event_objects(events: bytes) -> list[int]:
    seen: list[int] = []
    for off in range(0, len(events) - TAIL, EVENT):
        oid = struct.unpack_from("<I", events, off + EVENT_OBJECT_AT)[0] // 2
        if oid not in seen:
            seen.append(oid)
    return seen


def _object_groups(records) -> dict[int, int]:
    """object id -> group number, for the objects in a group."""
    out = {}
    for r in records:
        oid = object_id_of(r)
        if oid is not None:
            n = struct.unpack_from("<I", r.raw, HEADER + GROUP_AT)[0]
            if n:
                out[oid] = n
    return out


def _groups(records) -> list[Group]:
    triples = [t for t in sequences(records) if is_group(records[t.start].raw)]
    triples.sort(key=lambda t: t.slot)
    in_group = _object_groups(records)
    out = []
    for k, t in enumerate(triples):
        number = k + 1
        p = records[t.start].raw[HEADER:]
        members = _event_objects(records[t.end].raw[HEADER:])
        members = [m for m in members if in_group.get(m) == number]
        members += [oid for oid, n in in_group.items() if n == number and oid not in members]
        out.append(Group(number, t.slot, t.seq_id, _name_of(p), struct.unpack_from("<I", p, _flags_at(p))[0],
                         tuple(members), t.start))
    return out


def read_groups(data: bytes) -> list[Group]:
    """Every group, numbered as the Mixer's Group slot shows them."""
    return _groups(project_records(data))


def group_of(data: bytes) -> dict[int, int]:
    """object id -> group number, for every object in a group."""
    return _object_groups(project_records(data))


def _with_group(raw: bytes, number: int) -> bytes:
    buf = bytearray(raw)
    struct.pack_into("<I", buf, HEADER + GROUP_AT, number)
    return bytes(buf)


def _rebuild_events(raw: bytes, flags: int, members, values: dict[int, dict[str, int]]) -> bytes:
    events = raw[HEADER:]
    return rec(raw[:4], raw, _events_for(flags, members, values) + events[-TAIL:])


def _rewritten(data: bytes, groups: list[Group], changed: dict[int, tuple[bytes, bytes, tuple[int, ...]]],
               numbers: dict[int, int]) -> bytes:
    """``changed``: group number -> (qeSM raw, qSvE raw, members); ``numbers``: object id ->
    group number for every object whose number moves."""
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
            if oid in numbers:
                raw = _with_group(raw, numbers[oid])
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
        if r.tag == GNOS_TAG:
            raw = rec(GNOS_TAG, raw, register_group(raw[HEADER:], slot=slot, uuid=uuid))
        elif object_id_of(r) in members:
            raw = _with_group(raw, number)
        out.append(raw)
        if i == after:
            out += [qesm, marker, qsve]
    result = reassemble(data, out)
    moved = {m for m in members if old.get(m)}
    if moved:                                        # out of their old groups' event lists
        result = _drop_members(result, moved)
    require_valid(result)
    made = next(g for g in _groups(project_records(result)) if g.number == number)
    return result, made


def _drop_members(data: bytes, gone: set[int]) -> bytes:
    """Rebuild every group's events without ``gone`` — objects whose number no longer says
    they belong."""
    records = project_records(data)
    groups = _groups(records)
    values = _values(data)
    changed = {}
    for g in groups:
        events = records[g.start + 2].raw
        stale = set(_event_objects(events[HEADER:])) & gone
        if stale:
            keep = [m for m in _event_objects(events[HEADER:]) if m not in stale and m in g.members]
            keep += [m for m in g.members if m not in keep]
            changed[g.number] = (records[g.start].raw, _rebuild_events(events, g.flags, keep, values), tuple(keep))
    return _rewritten(data, groups, changed, {}) if changed else data


def assign(data: bytes, object_id: int, number: int) -> bytes:
    """Put ``object_id``'s track in group ``number`` (0 = no group): its object's number,
    an event per linked fader at the end of the group's list, and out of its old group."""
    require_full_walk(data)
    records = project_records(data)
    groups = _groups(records)
    by_number = {g.number: g for g in groups}
    if number and number not in by_number:
        raise ValueError(f"no group {number}; this project has {len(groups)}")
    if all(object_id_of(r) != object_id for r in records):
        raise ValueError(f"no channel object {object_id}")
    old = _object_groups(records).get(object_id, 0)
    if old == number:
        return data
    changed, values = {}, _values(data)
    if number:
        g = by_number[number]
        members = tuple(m for m in g.members if m != object_id) + (object_id,)
        changed[number] = (records[g.start].raw, _rebuild_events(records[g.start + 2].raw, g.flags, members, values), members)
    if old:
        g = by_number[old]
        members = tuple(m for m in g.members if m != object_id)
        changed[old] = (records[g.start].raw, _rebuild_events(records[g.start + 2].raw, g.flags, members, values), members)
    result = _rewritten(data, groups, changed, {object_id: number})
    require_valid(result)
    return result


def set_group(data: bytes, number: int, *, name: str | None = None, settings=None) -> bytes:
    """Rename group ``number`` and/or set its boxes; a changed fader set rewrites every
    member's events."""
    require_full_walk(data)
    records = project_records(data)
    groups = _groups(records)
    g = next((x for x in groups if x.number == number), None)
    if g is None:
        raise ValueError(f"no group {number}; this project has {len(groups)}")
    qesm = records[g.start].raw
    payload = qesm[HEADER:]
    flags = flags_for(settings, base=g.flags) if settings is not None else g.flags
    if name is not None:
        payload = _with_name(payload, name)
    payload = _with_flags(payload, flags)
    qsve = records[g.start + 2].raw
    if flags != g.flags:
        qsve = _rebuild_events(qsve, flags, g.members, _values(data))
    result = _rewritten(data, groups, {number: (rec(qesm[:4], qesm, payload), qsve, g.members)}, {})
    require_valid(result)
    return result


def group_errors(data: bytes) -> list[str]:
    """Where a project's three group structures disagree: an object numbered for a group
    that does not exist, a group whose events are not one per member per linked fader, a
    group slot without its registry pair."""
    from .registry import group_entries
    records = project_records(data)
    groups = _groups(records)
    numbers = {g.number for g in groups}
    out = [f"object {oid}: in group {n}, which does not exist"
           for oid, n in _object_groups(records).items() if n not in numbers]
    g_reg = next((r.raw[HEADER:] for r in records if r.tag == GNOS_TAG), None)
    for g in groups:
        events = records[g.start + 2].raw[HEADER:]
        want = sorted((m, FADERS.index(f)) for m in g.members for f in FADERS if g.flags >> FLAGS[f] & 1)
        have = sorted((struct.unpack_from("<I", events, k + EVENT_OBJECT_AT)[0] // 2,
                       _FADER_INDEX.get(events[k + EVENT_FADER_AT], -1))
                      for k in range(0, len(events) - TAIL, EVENT))
        if want != have:
            out.append(f"group {g.number}: {len(have)} event(s) for {len(g.members)} member(s), "
                       f"{len(want)} expected")
        if g_reg is not None and any(g.slot not in {s for _at, s in group_entries(g_reg, stride)}
                                     for stride in (24, 16)):
            out.append(f"group {g.number}: slot {g.slot} has no registry entry")
    return out
