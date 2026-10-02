"""Create a summing stack from existing arrange rows.

Logic's own Create Track Stack (Summing) over three tracks of a blank project
(`stack-summing-logic`): the header is an aux track — a grouping object bound to a stereo `Aux`
strip fed from a bus — its row where the first member sat, expanded; the members' rows follow one
level deeper with the header as their objects' parent, and each member's output goes to that bus.
The members' stack index (`+110`) stays as it was. What this writes:

* the header: an aux track as `addtrack.add_track` adds one (a fresh `Aux` strip after the
  highest; Logic's own bound the lowest free stub), its object cloned from Logic's own summing
  header — a session's aux tracks are not all grouping objects — and its strip carrying what
  Logic's summing aux carries beside a plain one, 90 at `+85` and `+119`
* the bus: the lowest `Bus N` nothing outputs to, is fed from or sends to, with a UUID of its
  own in place of the placeholder an unused bus carries
* the routing, as Logic wrote it twice over: the bus's UUID as each member's destination and the
  header's input, and its index in the member's output word and the header's input word
  (`binding`)
* the rows and parents, as `stack_create` writes a folder stack's

Direct members of one stack make a summing stack inside it (`nest-inner-summing-logic`): the
header's row takes their depth and its object the enclosing stack as parent, its strip's own
stack index stays 0, and the members go one deeper. A header as a member is refused.
`NumberOfTracks` in MetaData.plist is the caller's job.
"""

from __future__ import annotations

import struct

from .addtrack import add_track
from .binding import (
    INPUT_WORD_AT, OUTPUT_WORD_AT, bound_channels, channels, input_labels, output_labels,
    set_stack_index, stamp_uuids,
)
from .environment import DEFAULT_COLOUR, object_id_of, set_parent
from .mixer import device_inputs, is_mixer_record
from .recbuild import fresh_uuid, with_key
from .regions import sync_region_tracks
from .selection import select_track
from .sends import read_sends
from .stack_create import _members_in_order, packaged_aux
from .stacks import read_stacks, read_tracks, summing_around
from .stream import HEADER, project_records, reassemble
from .tracklist import EXPANDED_AT, EXPANDED_BIT, arrange_run, row_object, with_member
from .validate import require_full_walk, require_valid

SUMMING_AUX = {85: 90, 119: 90}                  # on Logic's summing aux; 0 on its plain new aux
BUS_PLACEHOLDER = bytes.fromhex("ee0000000000800080")   # how an unused bus's own UUID starts


def free_bus(data: bytes) -> int:
    """Owner of the lowest `Bus N` no channel outputs to, is fed from or sends to."""
    used = {label for labels in (output_labels(data), input_labels(data)) for label in labels.values() if label}
    used |= {f"Bus {s.bus}" for sends in read_sends(data).values() for s in sends}
    buses = sorted((int(c.label[4:]), owner) for owner, c in channels(data).items()
                   if c.label.startswith("Bus ") and c.label[4:].isdigit())
    for number, owner in buses:
        if f"Bus {number}" not in used:
            return owner
    raise ValueError("every bus is in use")


def _require_one_destination(data: bytes, rows: list[dict], stacks: list, members: list[int]) -> None:
    """Refuse members that output anywhere but where the new aux will: Logic's own stack was
    measured over tracks already on that output, so where it sends the aux otherwise is not known."""
    from .stack_place import summing_bus
    keys = {r["object_id"]: r for r in rows}
    around = summing_around(stacks, keys[members[0]]["key"])
    destination = summing_bus(data, around) if around is not None else "Output 1-2"
    owners, outputs = bound_channels(data), output_labels(data)
    for m in members:
        out = outputs.get(owners.get(m))
        if out != destination:
            raise ValueError(f"{keys[m]['name']!r} outputs to {out or 'nothing'}, not {destination}: where "
                             "Logic sends a summing stack's aux when its members go elsewhere is not measured")


def _routed(raw: bytes, *, word_at: int, word: int, **uuids: bytes) -> bytes:
    buf = bytearray(raw)
    struct.pack_into("<H", buf, HEADER + word_at, word)
    return stamp_uuids(bytes(buf), **uuids)


def create_summing_stack(data: bytes, *, name: str, members: list[int], track_count: int | None = None,
                         colour: int = DEFAULT_COLOUR) -> tuple[bytes, dict]:
    """A summing stack ``name`` over the arrange rows of ``members`` (any order)."""
    if not members:
        raise ValueError("a stack needs at least one member")
    require_full_walk(data)
    rows, stacks = read_tracks(data, track_count), read_stacks(data, track_count)
    ordered, depth, inside = _members_in_order(rows, members, stacks)
    _require_one_destination(data, rows, stacks, ordered)
    bus_label = channels(data)[free_bus(data)].label
    data, report = add_track(data, name=name, after=ordered[-1], kind="aux", colour=colour,
                             member=None, track_count=track_count,
                             pattern_object=packaged_aux(project_records(data))["object"])
    count = None if track_count is None else track_count + 1
    header = report["object_id"]

    chans, owners_of = channels(data), bound_channels(data)        # the add moved the owners above it
    bus_owner = next(o for o, c in chans.items() if c.label == bus_label)
    bus = chans[bus_owner]
    bus_uuid = fresh_uuid() if bus.uuid.startswith(BUS_PLACEHOLDER) else bus.uuid
    word = int(bus_label[4:]) - 1 + device_inputs(data) // 2
    header_owner, member_owners = owners_of[header], {owners_of[m] for m in ordered}

    records = project_records(data)
    run = arrange_run(records, count)
    rows = [records[i].raw for i in run]
    member_set = set(ordered)
    head = bytearray(next(raw for raw in rows if row_object(raw) == header))
    head[HEADER + EXPANDED_AT] |= EXPANDED_BIT
    kept = [raw for raw in rows if row_object(raw) not in member_set | {header}]
    at = next(k for k, raw in enumerate(rows) if row_object(raw) == ordered[0])
    rows = (kept[:at] + [bytes(head)]
            + [with_member(raw, depth + 1) for raw in rows if row_object(raw) in member_set] + kept[at:])
    replace = dict(zip(run, (with_key(raw, key) for key, raw in enumerate(rows)), strict=True))

    out = []
    for i, r in enumerate(records):
        raw = replace.get(i, r.raw)
        if object_id_of(r) in member_set:
            raw = set_parent(raw, header)
        elif object_id_of(r) == header and inside is not None:
            raw = set_parent(raw, inside)
        elif is_mixer_record(r) and r.owner == header_owner:
            buf = bytearray(set_stack_index(raw, 0))
            for off, value in SUMMING_AUX.items():
                buf[HEADER + off] = value
            raw = _routed(bytes(buf), word_at=INPUT_WORD_AT, word=word, source=bus_uuid)
        elif is_mixer_record(r) and r.owner in member_owners:
            raw = _routed(raw, word_at=OUTPUT_WORD_AT, word=word, destination=bus_uuid)
        elif is_mixer_record(r) and r.owner == bus_owner:
            raw = stamp_uuids(raw, own=bus_uuid)
        out.append(raw)

    result = sync_region_tracks(reassemble(data, out), count)
    result = select_track(result, header, count)
    require_valid(result)
    return result, {**report, "bus": bus_label, "members": ordered}
