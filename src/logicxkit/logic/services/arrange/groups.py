"""Logic groups — the Mixer's Group slot. Measured on twenty-eight single-change saves
(Logic Pro 12.3.1, 2026-09-05: a group made, a second member, a second group, a rename, and
every box in Group Settings toggled one at a time).

A group is a sequence triple of its own — `qeSM` / zero-size `karT` / `qSvE` with header
`+6` = 0x11 — placed after the last `rpyH` record and before the first `ivnE`, one per
group in slot order (`+10` = 0, 4, 8 ...; group N sits in slot 4(N-1)). The `qeSM` payload:

    +8        u32   id, repeated as the `qSvE`'s owner; any unused triple id
    +16       u16   name length in bytes; the name follows as UTF-8, padded to an even length
    +70+name  u32   the settings, one bit per box (FLAGS); 0x81400005 on a fresh group

The `qSvE` holds one 32-byte event per member per linked fader — Volume, Mute, Solo and
Pan; every other box is flag-only — then a 16-byte tail. Event `+4` is the member's object
id doubled, `+12` the fader as Logic numbers them (7 Volume, 9 Mute, 3 Solo, 10 Pan), `+8`
the member's value for it as the channel stores it (the fader's fixed-point word; the pan
byte in the top byte), its halves repeated at `+20` and `+30`. Logic's own saves can lack
them: a switched-off group carries none (`songb-bars-9-12-logic`), Logic 12.4's re-saves of
sessions dropped every Volume event and kept the Mute ones (`tracking-template-12-4`), and
Logic 12.3.1 wrote missing Volume events back on its next save (`width-tracking-logic`). A
member's `ivnE` carries a **bitmask of its groups** at `+24` (bit N-1 = group N; 0 = none — a
channel in groups 1 and 4 reads 9), and the registry holds a `<0x11><slot>` entry per group
in both runs, directly before the object entries. The row's `+4` and the channel's `+92` do
not change. Bit 31 of
the flags is the table's **On** box (clear on a switched-off group; measured on two groups
switched off). Create Group in Logic sets the new bit and leaves a member's other groups and
their events alone; leaving is composed here (the member's events go, its bit clears).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from .environment import object_id_of
from ..stream.stream import HEADER, project_records
from ..stream.registry import GNOS_TAG
from ..stream.sequence import is_group, sequences

GROUP_AT = 24                       # ivnE: u32 bitmask of the member's groups, bit N-1 = group N
ID_AT, NAME_AT = 8, 16
FLAGS_AFTER_NAME = 70
SLOT_STEP = 4
EVENT, TAIL = 32, 16
EVENT_OBJECT_AT, EVENT_FADER_AT, EVENT_VALUE_AT = 4, 12, 8
EVENT_VALUE_HI_AT, EVENT_VALUE_LO_AT = 20, 30
DEFAULT_FLAGS = 0x81400005
GROUP_ON = 1 << 31                  # the table's On box (clear on a switched-off group)
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
EVENT_ORDER = ("Solo", "Pan", "Mute", "Volume")   # as Logic's saves order a member's events: Solo before Pan on `group-hide-logic`
                                                   # and `group-solo-logic`, Pan before Mute before Volume on 13.0's (2026-11-13)
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
    def on(self) -> bool:
        return bool(self.flags & GROUP_ON)

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


def _name_of(payload: bytes) -> str:
    n = struct.unpack_from("<H", payload, NAME_AT)[0]
    raw = payload[NAME_AT + 2:NAME_AT + 2 + n]
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def _flags_at(payload: bytes) -> int:
    n = struct.unpack_from("<H", payload, NAME_AT)[0]
    return FLAGS_AFTER_NAME + n + (n & 1)


def _event_objects(events: bytes) -> list[int]:
    seen: list[int] = []
    for off in range(0, len(events) - TAIL, EVENT):
        oid = struct.unpack_from("<I", events, off + EVENT_OBJECT_AT)[0] // 2
        if oid not in seen:
            seen.append(oid)
    return seen


def _bit(number: int) -> int:
    return 1 << (number - 1)


def _numbers(mask: int) -> tuple[int, ...]:
    return tuple(n for n in range(1, mask.bit_length() + 1) if mask & _bit(n))


def _object_groups(records) -> dict[int, int]:
    """object id -> group mask, for the objects in at least one group."""
    out = {}
    for r in records:
        oid = object_id_of(r)
        if oid is not None:
            mask = struct.unpack_from("<I", r.raw, HEADER + GROUP_AT)[0]
            if mask:
                out[oid] = mask
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
        members = [m for m in members if in_group.get(m, 0) & _bit(number)]
        members += [oid for oid, mask in in_group.items() if mask & _bit(number) and oid not in members]
        out.append(Group(number, t.slot, t.seq_id, _name_of(p), struct.unpack_from("<I", p, _flags_at(p))[0],
                         tuple(members), t.start))
    return out


def read_groups(data: bytes) -> list[Group]:
    """Every group, numbered as the Mixer's Group slot shows them."""
    return _groups(project_records(data))


def group_of(data: bytes) -> dict[int, tuple[int, ...]]:
    """object id -> its group numbers, for every object in at least one group."""
    return {oid: _numbers(mask) for oid, mask in _object_groups(project_records(data)).items()}


def _linked_events(records, g: Group) -> tuple[set[tuple[int, int]], list[tuple[int, int]]]:
    """(member, fader) pairs the group's boxes call for, and the pairs its event list holds."""
    events = records[g.start + 2].raw[HEADER:]
    want = {(m, FADERS.index(f)) for m in g.members for f in FADERS if g.flags >> FLAGS[f] & 1}
    have = [(struct.unpack_from("<I", events, k + EVENT_OBJECT_AT)[0] // 2,
             _FADER_INDEX.get(events[k + EVENT_FADER_AT], -1))
            for k in range(0, len(events) - TAIL, EVENT)]
    return want, have


def missing_group_events(data: bytes) -> int:
    """How many member events the groups' boxes call for and their lists lack. Logic's own saves
    lack some, so this is a count to hold a write to, not a fault."""
    records = project_records(data)
    return sum(len(want - set(have)) for want, have in (_linked_events(records, g) for g in _groups(records)))


def group_errors(data: bytes) -> list[str]:
    """Where a project's three group structures disagree: an object numbered for a group
    that does not exist, a group event for a track or fader the group does not link, a group
    slot without its registry pair. A missing event is no error: Logic's own saves lack them."""
    from ..stream.registry import group_entries
    records = project_records(data)
    groups = _groups(records)
    numbers = {g.number for g in groups}
    out = [f"object {oid}: in group {n}, which does not exist"
           for oid, mask in _object_groups(records).items() for n in _numbers(mask) if n not in numbers]
    g_reg = next((r.raw[HEADER:] for r in records if r.tag == GNOS_TAG), None)
    for g in groups:
        want, have = _linked_events(records, g)
        stray = len(have) - len(set(have) & want)
        if stray:
            out.append(f"group {g.number}: {stray} event(s) for a track or a fader it does not link, or repeated")
        if g_reg is not None and any(g.slot not in {s for _at, s in group_entries(g_reg, stride)}
                                     for stride in (24, 16)):
            out.append(f"group {g.number}: slot {g.slot} has no registry entry")
    return out
