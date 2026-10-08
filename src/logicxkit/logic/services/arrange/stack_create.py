"""Create a folder stack from existing arrange rows (`stack_summing` makes a summing one).

Logic's own Create Track Stack on a blank project is the packaged pattern for a session that has
no stack; otherwise this composes the measured pieces — a track add (`addtrack.py`), a drag into
a stack (`stacks.move_to_stack`) and the `Sub` strips the existing stacks bind to. A folder stack is a kind-0 Environment object bound to a `Sub N`
strip, its arrange row followed by its members' rows with `+14` set. What this writes:

* the object: the highest-numbered folder stack's, cloned — new id, name, colour, Sub number,
  fresh UUID; the icon stays the pattern's (which icon Logic gives a new stack is unmeasured)
* the strip: the lowest `Sub` strip out of use, put back in use under the new object's UUID
  and nothing else of it changed (`stack-sub-gap-after-logic`,
  `stack-sub-after-convert-after-logic`); with none, a `Sub` numbered after the highest, in use
  or not, cloned right after it (`stack-sub-after-flatten-after-logic`), every later channel's
  owner moved up by one (and the objects bound to them re-indexed), the channel count's
  Master+Sub class counted up
* the rows: a header row where the first member sat, expanded and selected; the member rows
  behind it in arrange order with `+14 = 1` and their channels' stack index set as a drag sets
  them. The members' parent pointers stay as they were and the header takes that pointer —
  the summing stack they sit in, none inside a plain folder or at the top level — and Logic's
  colour 20 for a new folder header (six of Logic's own creates, `stack-sub-level-after-logic`,
  `nest-inner-folder-logic` and the rest, 2026-10-04/06)
* the flat mixer-order row after the last Sub's, the sequence triple, the index-table entry
  and the `gnoS` registry entries, as a track add writes them

Members that are direct members of one stack make a stack inside it: the header's row takes
their depth and theirs go one deeper, the new strip's own stack index stays 0 and no parent is
set on the header, as Logic's own Create Track Stack inside a folder wrote them
(`nest-inner-folder-logic`). A header as a member makes a stack around that stack: its rows go
one deeper with it and its strip takes the new stack's index (`nest-stack-in-stack-logic`,
`stack-folder-around-summing-after-logic`). A third level is refused: Logic's Create Track
Stack is disabled wherever it would make one (`stacks.require_two_levels`).
`NumberOfTracks` in MetaData.plist is the caller's job.
"""

from __future__ import annotations

import struct

from ..mixer.binding import IN_USE_AT, bound_channels, channels, set_stack_index, stamp_uuids
from ..mixer.channel_alloc import (
    COUNT_CLASS_AT, NUMBER_AT, bump_channel_count, is_channel_record, is_mixer_record, mixer_record,
    new_sub_channel, project_words, shifted_channel,
)
from ..mixer.levels import FADER_AT, FADER_FIXED_AT, FIXED_ONE, MUTE_AT, PAN_CENTRE, UNITY, read_levels
from ..mixer.mixer import is_channel_count
from .environment import (
    ENV_TAG,
    UUID_LEN,
    channel_objects,
    clone_object,
    object_id_of,
    object_record,
    object_stamp,
    set_parent,
    shifted_object,
)
from ..stream.stream import HEADER, NO_KEY, project_records, reassemble
from ..stream.keyflags import sync_key_flags
from ..stream.recbuild import fresh_uuid, rec
from ..stream.registry import GNOS_TAG, register_object
from .stack_ids import FOLDER_COLOUR, free_object_id
from .stack_pattern import first_stack
from ..regions.regions import sync_region_tracks, sync_row_count
from .selection import select_track
from ..stream.sequence import plan_sequence
from ..stream.table_index import sync_indices
from .stacks import read_stacks, read_tracks, require_two_levels, span_end
from .tracklist import (
    MEMBER_AT,
    arrange_run,
    clone_flat_row,
    flat_run,
    new_row,
    renumbered,
    row_object,
    with_member,
)
from ..stream.validate import require_full_walk, require_valid

SUB_NUMBER_AT = NUMBER_AT


def _strip_for(data: bytes, chans) -> tuple[int, int, bool]:
    """``(number, owner, reused)`` of the new stack's `Sub` strip: the lowest one out of use,
    else a new one numbered after the highest and placed right after it (after Master with
    none). Logic's reuse puts the strip's fader at 0 dB and clears its mute
    (`stack-sub-level-after-logic`, `stack-sub-muted-after-logic`); a pan, a solo, an insert or
    a send on one is not measured and is refused."""
    subs = {int(c.label[4:]): o for o, c in chans.items() if c.label.startswith("Sub ") and c.label[4:].isdigit()}
    free = sorted(n for n, o in subs.items() if not chans[o].in_use)
    if free:
        owner = subs[free[0]]
        level = read_levels(data)[owner]
        carried = [what for what, off in (("a pan", level["pan"] != PAN_CENTRE), ("a solo", level["solo"])) if off]
        carried += ["an insert or a send"] * any(r.tag == b"UCuA" and r.owner == owner for r in project_records(data))
        if carried:
            raise ValueError(f"Sub {free[0]} is out of use and is the strip Logic would take, but it carries "
                             f"{', '.join(carried)}: what Logic's reuse does with that is not measured")
        return free[0], owner, True
    if subs:
        return max(subs) + 1, subs[max(subs)] + 1, False
    master = next((o for o, c in chans.items() if c.label == "Master"), None)
    if master is None:
        raise ValueError("no Master strip to place Sub 1 after")
    return 1, master + 1, False


def _members_in_order(rows: list[dict], members: list[int], stacks: list) -> tuple[list[int], int, int | None]:
    """The members in arrange order, the depth they share and the object of the stack that holds
    them (None at the top level). They are refused unless they sit side by side in one place:
    all at the top level, or all direct members of one stack."""
    by_object = {r["object_id"]: r for r in rows}
    holder = {key: s.object_id for s in stacks for key, _name in s.members}
    for m in members:
        if m not in by_object:
            raise ValueError(f"object {m} is not in the arrange list")
    places = {(by_object[m]["depth"], holder.get(by_object[m]["key"])) for m in members}
    if len(places) != 1:
        raise ValueError("the members sit in more than one stack or level; a stack is made at the top "
                         "level or from direct members of one stack")
    (depth, inside), = places
    if depth and inside is None:
        raise ValueError("the members sit under a row that is not read as a stack")
    inside_key = next((s.track_key for s in stacks if s.object_id == inside), None)
    require_two_levels(stacks, inside_key, [by_object[m]["key"] for m in members], new=1)
    return sorted(set(members), key=lambda m: by_object[m]["key"]), depth, inside


def moved_in(rows: list[bytes], members: set[int], headers: set[int]) -> tuple[list[bytes], set[int]]:
    """The members' rows one level deeper, a stack among them with the rows it holds, and the
    objects of every row moved."""
    depths = [raw[HEADER + MEMBER_AT] for raw in rows]
    moved, objects = [], set()
    for k, raw in enumerate(rows):
        if row_object(raw) in members:
            for j in range(k, span_end(depths, k)):
                moved.append(with_member(rows[j], depths[j] + 1, header=row_object(rows[j]) in headers))
                objects.add(row_object(rows[j]))
    return moved, objects


def _flat_place(records, flat: list[int], owners_of: dict, chans: dict, number: int) -> int:
    """The mixer-order row the new header's goes after, -1 for the head of the list: the `Sub`
    rows stay in strip order there (`stack-sub-gap-after-logic`), and with no `Sub` row the new
    one goes last."""
    rows = []
    for k, i in enumerate(flat):
        chan = chans.get(owners_of.get(row_object(records[i].raw)))
        if chan is not None and chan.label.startswith("Sub ") and chan.label[4:].isdigit():
            rows.append((k, int(chan.label[4:])))
    lower = [k for k, n in rows if n < number]
    if lower:
        return max(lower)
    return min(k for k, _n in rows) - 1 if rows else len(flat) - 1


def create_stack(data: bytes, *, name: str, members: list[int], track_count: int | None = None,
                 colour: int | None = None) -> tuple[bytes, dict]:
    """A folder stack ``name`` holding the arrange rows of ``members`` (any order), coloured
    ``colour`` (Logic's 20 for a new folder when not given)."""
    if not members:
        raise ValueError("a stack needs at least one member")
    colour = FOLDER_COLOUR if colour is None else colour
    require_full_walk(data)
    records = project_records(data)
    objs = channel_objects(data)
    chans = channels(data)
    owners_of = bound_channels(data)
    stacks = read_stacks(data, track_count)
    ordered, depth, _inside = _members_in_order(read_tracks(data, track_count), members, stacks)
    run = arrange_run(records, track_count)
    run_rows = [records[i].raw for i in run]
    folders = [s for s in stacks if s.kind == "folder"]   # a summing stack's Aux number would outrank the Subs
    if folders:
        pattern = max(folders, key=lambda s: s.index)
        like = pattern.object_id
        pattern_obj = object_record(records, like)
        strip_template = mixer_record(records, pattern.owner)
        row_template = next(raw for raw in run_rows if row_object(raw) == like)
    else:
        like, pattern_obj, strip_template, row_template = first_stack(data, records)
    number, owner, reused = _strip_for(data, chans)
    label = f"Sub {number}"
    object_id, reused_id = free_object_id(records, objs, track_count)   # a gone object's: its entries kept, its parked row dropped
    top = max(objs)
    plan = plan_sequence(records, like=like, object_id=object_id, reuse=reused_id)

    pattern_stamp = object_stamp(pattern_obj)
    parents = {objs[m].parent for m in ordered if m in objs}
    if len(parents) > 1:
        raise ValueError(f"the members sit under different parents {sorted(parents)}; Logic's create would not offer this")
    new_obj = set_parent(clone_object(pattern_obj, object_id=object_id, name=name, owner=owner,
                                      colour=colour, icon=None, stack_number=number), parents.pop() if parents else 0)
    last_env = max(i for i, r in enumerate(records) if r.tag == ENV_TAG)
    # its own stack index stays 0 inside another stack too, as on Logic's own (`nest-inner-folder-logic`)
    new_chan = set_stack_index(new_sub_channel(strip_template, number=number, owner=owner, uuid=new_obj[-UUID_LEN:],
                                               words=project_words(data)), 0)
    strip_before = None if reused else max(i for i, r in enumerate(records)
                                           if is_channel_record(r) and r.owner == owner - 1)

    member_set = set(ordered)
    header = new_row(row_template, object_id=object_id, member=depth, expanded=True)
    moved, taken = moved_in(run_rows, member_set, {s.object_id for s in stacks})
    at = next(k for k, raw in enumerate(run_rows) if row_object(raw) == ordered[0])
    kept = [raw for raw in run_rows if row_object(raw) not in taken]
    new_rows = kept[:at] + [header] + moved + kept[at:]

    flat = flat_run(records, run)
    flat_pos = _flat_place(records, flat, owners_of, chans, number)
    flat_row = clone_flat_row(records[flat[max(flat_pos, 0)]].raw, object_id)
    member_owners = {owners_of[m] for m in ordered if m in owners_of}
    gnos_uuid = fresh_uuid()

    out: list[bytes] = []
    run_set = set(run)
    flat_set = set(flat)
    for i, r in enumerate(records):
        if i in run_set:
            if i == run[0]:
                out += new_rows
            continue
        if reused_id and i in flat_set and row_object(r.raw) == object_id:
            if flat_pos >= 0 and i == flat[flat_pos]:
                out.append(flat_row)
            continue
        if flat_pos < 0 and i == flat[0]:
            out.append(flat_row)
        raw = plan.rewrite(i, r)
        oid = object_id_of(r)
        if oid is not None:
            bound = owners_of.get(oid)
            raw = shifted_object(raw, channel=not reused and bound is not None and bound >= owner,
                                 stamp=object_stamp(raw) > pattern_stamp)
        elif is_mixer_record(r) and r.owner in member_owners:
            raw = set_stack_index(raw, number)
        elif reused and is_mixer_record(r) and r.owner == owner and r.key == NO_KEY:
            buf = bytearray(raw)
            buf[HEADER + IN_USE_AT] = buf[HEADER + IN_USE_AT + 1] = 1
            buf[HEADER + FADER_AT[0]] = UNITY
            struct.pack_into("<I", buf, HEADER + FADER_FIXED_AT, UNITY * FIXED_ONE)
            buf[HEADER + MUTE_AT] &= ~1 & 0xff
            raw = stamp_uuids(bytes(buf), own=new_obj[-UUID_LEN:])
        elif is_channel_count(r) and not reused:
            raw = bump_channel_count(raw, class_at=COUNT_CLASS_AT["Sub"])
        elif r.tag == GNOS_TAG:
            raw = rec(GNOS_TAG, raw, register_object(raw[HEADER:], object_id=object_id, top=top,
                                                     uuid=gnos_uuid, slot=plan.slot))
        if not reused and is_channel_record(r) and r.owner >= owner:
            raw = shifted_channel(raw, r, relabel_prefix="Sub ")
        out.append(raw)
        if flat_pos >= 0 and i == flat[flat_pos]:
            out.append(flat_row)
        if i == plan.insert_after:
            out += plan.new
        if i == last_env:
            out.append(new_obj)
        if i == strip_before:
            out.append(new_chan)

    result = reassemble(data, out)
    result = reassemble(result, renumbered(project_records(result)))
    result = sync_key_flags(result)                  # a cloned channel carries its pattern's flags
    result = sync_row_count(result, None if track_count is None else track_count + 1)
    result = sync_region_tracks(result, None if track_count is None else track_count + 1)
    result = select_track(result, object_id, None if track_count is None else track_count + 1)
    result = reassemble(result, sync_indices(project_records(result), None if track_count is None else track_count + 1))
    require_valid(result)
    return result, {"object_id": object_id, "owner": owner, "label": label,
                    "sequence": plan.index, "slot": plan.slot, "members": ordered}
