"""Create a summing stack from existing arrange rows.

Logic's own Create Track Stack (Summing) over three tracks of a blank project
(`stack-summing-logic`): the header is an aux track — a grouping object bound to a stereo `Aux`
strip fed from a bus — its row where the first member sat, expanded; the members' rows follow one
level deeper with the header as their objects' parent, and each member's output goes to that bus.
The members' stack index (`+110`) stays as it was. What this writes:

* the header: an aux track as `addtrack.add_track` adds one, on the lowest free `Aux` stub as
  Logic's own (a fresh `Aux` strip after the highest when none is free), its object cloned from
  Logic's own summing header — a session's aux tracks are not all grouping objects — and its
  strip carrying what Logic's summing aux carries beside a plain new one, 90 at `+85` and `+119`
  (a stub has them already)
* the bus: the lowest `Bus N` nothing outputs to, is fed from or sends to, with a UUID of its
  own in place of the placeholder an unused bus carries
* the routing, as Logic wrote it twice over: the bus's UUID as each member's destination and the
  header's input, and its index in the member's output word and the header's input word
  (`binding`)
* the header's output: where every member's went when they share one, Output 1-2 when they
  differ (`stack-summing-shared-*`, `stack-summing-differ-logic`,
  `nest-summing-in-summing-*`) — inside another summing stack too, where it takes that
  stack's bus only because its members were on it. A shared bus still on its placeholder UUID
  counts as no shared output (`stack-summing-placeholder-*`)
* the rows and parents, as `stack_create` writes a folder stack's

Direct members of one stack make a summing stack inside it (`nest-inner-summing-logic`): the
header's row takes their depth and its object the enclosing stack as parent, its strip's own
stack index stays 0, and the members go one deeper. A folder stack as a member goes in with its
rows, and the tracks it holds are the ones routed to the bus and given the header as parent
(`stack-summing-around-folder-after-logic`); the folder has no output of its own, so the stack
goes to Output 1-2 and no bus's aux is reused, whatever its tracks fed
(`stack-summing-busfolder-after-logic`). A summing stack as a member is routed by its aux,
its own members left on its bus (`stack-summing-around-summing-after-logic`). Members that are
all their bus has get no new aux: that bus's own becomes the main track (`stack_reuse`).
`NumberOfTracks` in MetaData.plist is the caller's job.
"""

from __future__ import annotations

import struct

from .addtrack import add_track
from ..mixer.binding import (
    INPUT_WORD_AT, OUTPUT_WORD_AT, bound_channels, channels, input_labels, output_labels,
    set_stack_index, stamp_uuids,
)
from .environment import channel_objects, object_id_of, set_parent
from ..mixer.mixer import device_inputs, is_mixer_record
from ..mixer.routing import set_output
from ..stream.recbuild import fresh_uuid, with_key
from ..regions.regions import sync_region_tracks
from .selection import select_track
from ..mixer.sends import read_sends
from .stack_create import _members_in_order, moved_in
from .stack_pattern import packaged_aux
from .stacks import FOLDER, read_stacks, read_tracks
from ..stream.stream import HEADER, project_records, reassemble
from .tracklist import EXPANDED_AT, EXPANDED_BIT, arrange_run, row_object
from ..stream.validate import require_full_walk, require_valid

SUMMING_AUX = {85: 90, 119: 90}                  # on Logic's summing aux; 0 on its plain new aux
MAIN_OUTPUT = "Output 1-2"
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


def shared_output(data: bytes, outputs: list[str | None]) -> str | None:
    """The output every member has, None when they differ or the one they share is a bus on
    its placeholder UUID."""
    if len(set(outputs)) != 1 or outputs[0] is None:
        return None
    label = outputs[0]
    bus = next((c for c in channels(data).values() if c.label == label and label.startswith("Bus ")), None)
    return None if bus is not None and bus.uuid.startswith(BUS_PLACEHOLDER) else label


def own_aux(data: bytes, bus: str, members: set[int]) -> int | None:
    """Owner of the one aux fed from ``bus`` when the channels ``members`` are all that outputs
    to it and nothing sends to it: the aux Logic makes the main track in place of a new one. A
    send to the bus is unmeasured and counts as another feeder."""
    chans, outs, ins = channels(data), output_labels(data), input_labels(data)
    feeders = {o for o, label in outs.items() if label == bus and chans[o].in_use}
    sent = {f"Bus {s.bus}" for sends in read_sends(data).values() for s in sends}
    fed = [o for o, c in chans.items() if c.in_use and c.label.startswith("Aux ") and ins.get(o) == bus]
    return fed[0] if feeders == members and bus not in sent and len(fed) == 1 else None


def _routed(raw: bytes, *, word_at: int, word: int, **uuids: bytes) -> bytes:
    buf = bytearray(raw)
    struct.pack_into("<H", buf, HEADER + word_at, word)
    return stamp_uuids(bytes(buf), **uuids)


def _routed_tracks(ordered: list[int], rows: list[dict], stacks: list) -> list[int]:
    """The tracks a stack over ``ordered`` sends to its bus: each member, a summing stack's main
    track among them, and for a folder stack the tracks it holds."""
    by_object, by_key = {s.object_id: s for s in stacks}, {r["key"]: r["object_id"] for r in rows}
    out = []
    for m in ordered:
        stack = by_object.get(m)
        out += [m] if stack is None or stack.kind != FOLDER else [by_key[key] for key, _name in stack.members]
    return out


def create_summing_stack(data: bytes, *, name: str, members: list[int], track_count: int | None = None,
                         colour: int | None = None) -> tuple[bytes, dict]:
    """A summing stack ``name`` over the arrange rows of ``members`` (any order). With no
    ``colour`` the header takes its first member's, as every summing header Logic made has it
    (`stack-summing-busfolder-after-logic`, `stack-summing-reuse-colour-after-logic`)."""
    if not members:
        raise ValueError("a stack needs at least one member")
    require_full_walk(data)
    rows, stacks = read_tracks(data, track_count), read_stacks(data, track_count)
    ordered, depth, inside = _members_in_order(rows, members, stacks)
    routed = _routed_tracks(ordered, rows, stacks)
    bound, outputs = bound_channels(data), output_labels(data)
    names = {r["object_id"]: r["name"] for r in rows}
    unbound = [names[m] for m in dict.fromkeys(ordered + routed) if m not in bound]
    if unbound:
        raise ValueError(f"{', '.join(map(repr, unbound))}: a track with no channel has no output for a "
                         "summing stack to send to its bus")
    went = {m: outputs.get(bound.get(m)) for m in routed}
    folders = {s.object_id for s in stacks if s.kind == FOLDER}
    shared = shared_output(data, [None if m in folders else outputs.get(bound.get(m)) for m in ordered])
    reused = own_aux(data, shared, {bound[m] for m in ordered}) if shared and shared.startswith("Bus ") else None
    if reused is not None:
        if any(s.object_id in ordered for s in stacks):
            raise ValueError(f"the members all output to {shared}, which only they feed, and a summing stack is "
                             "among them: what Logic makes the main track then is not measured")
        from .stack_reuse import main_track_from_aux
        return main_track_from_aux(data, bus=shared, aux_owner=reused, members=ordered, inside=inside,
                                   track_count=track_count)
    target = shared or MAIN_OUTPUT
    if colour is None:
        colour = channel_objects(data)[ordered[0]].colour
    bus_label = channels(data)[free_bus(data)].label
    data, report = add_track(data, name=name, after=ordered[-1], kind="aux", colour=colour,
                             member=None, track_count=track_count, bind_stub=True,
                             pattern_object=packaged_aux(project_records(data))["object"])
    count = None if track_count is None else track_count + 1
    header = report["object_id"]

    chans, owners_of = channels(data), bound_channels(data)        # the add moved the owners above it
    bus_owner = next(o for o, c in chans.items() if c.label == bus_label)
    bus = chans[bus_owner]
    bus_uuid = fresh_uuid() if bus.uuid.startswith(BUS_PLACEHOLDER) else bus.uuid
    word = int(bus_label[4:]) - 1 + device_inputs(data) // 2
    header_owner, member_owners = owners_of[header], {owners_of[m] for m in routed}

    records = project_records(data)
    run = arrange_run(records, count)
    rows = [records[i].raw for i in run]
    member_set = set(ordered) | set(routed)
    head = bytearray(next(raw for raw in rows if row_object(raw) == header))
    head[HEADER + EXPANDED_AT] |= EXPANDED_BIT
    moved, taken = moved_in(rows, set(ordered), {s.object_id for s in stacks})
    kept = [raw for raw in rows if row_object(raw) not in taken | {header}]
    at = next(k for k, raw in enumerate(rows) if row_object(raw) == ordered[0])
    rows = kept[:at] + [bytes(head)] + moved + kept[at:]
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
    result = set_output(result, header_owner, next(o for o, c in channels(result).items() if c.label == target))
    require_valid(result)
    return result, {**report, "bus": bus_label, "members": ordered, "output": target,
                    "left": {names[m]: went[m] for m in routed if went[m] != target},
                    "reused": False, "tracks_added": 1, "name": name}
