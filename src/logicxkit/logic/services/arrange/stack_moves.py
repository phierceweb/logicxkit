"""A track into a stack and out of it, as Logic's own drags leave the rows, parents, stack
indices and, into a summing stack, the routing."""

from __future__ import annotations

from ..mixer.binding import bound_channels, set_stack_index
from .environment import object_id_of, set_parent, set_selected_object
from ..mixer.mixer import CHANNEL_TAG
from ..stream.recbuild import with_key
from ..regions.regions import sync_region_tracks, sync_row_count
from .selection import select_track
from .stack_place import summing_bus, to_summing_bus
from .stacks import FOLDER, SUMMING, read_stacks, require_two_levels, span_end, summing_holder
from ..stream.stream import HEADER, NO_KEY, project_records, reassemble
from .tracklist import MEMBER_AT, arrange_run, row_object, with_member
from ..stream.validate import require_full_walk, require_valid


def move_to_stack(data: bytes, track_object: int, stack_object: int,
                  track_count: int | None = None) -> bytes:
    """Move a track into a stack the way Logic does — from the top level or from another
    stack (both measured on Logic's own drags, 2026-09-04): reposition the row as the last
    member, set its member byte, stamp the parent pointer, set the stack index on the
    track's mixer channel, and leave the track selected. Into a summing stack its parent and
    stack index stay (`stack-summing-dragged-in-logic`) and it outputs to the stack's bus; a
    stack moved in takes its members along, a summing one's aux onto the bus, a folder's rows
    alone (`stack_place`). Refuses an invalid result."""
    require_full_walk(data)
    records = list(project_records(data))
    run = arrange_run(records, track_count)
    order = [row_object(records[i].raw) for i in run]
    if track_object not in order:
        raise ValueError(f"track object {track_object} is not in the arrange list")
    stacks = {s.object_id: s for s in read_stacks(data, track_count)}
    if stack_object not in stacks:
        raise ValueError(f"object {stack_object} is not a stack")
    stack = stacks[stack_object]
    summing = stack.kind == SUMMING
    require_two_levels(list(stacks.values()), stack.track_key, [order.index(track_object)])
    was = summing_holder(list(stacks.values()), order.index(track_object))
    folder_moved = track_object in stacks and stacks[track_object].kind == FOLDER     # no output of its own
    routed = summing and not folder_moved and (was is None or was.object_id != stack_object)
    if routed and summing_bus(data, stack) is None:
        raise ValueError(f"{stack.name!r} is fed from no bus, so a track moved into it has nowhere to go")

    depths = [records[i].raw[HEADER + MEMBER_AT] for i in run]
    start = order.index(stack_object)
    end = span_end(depths, start)
    pos = order.index(track_object)
    if start < pos < end and depths[pos] == stack.depth + 1:
        return data                                   # already a direct member
    block_end = span_end(depths, pos)                 # a moving stack takes its members along
    if pos <= start < block_end:
        raise ValueError("a stack cannot move into one of its own members")

    rows = [records[i].raw for i in run]
    shift = stack.depth + 1 - depths[pos]
    block = [with_member(rows[k], depths[k] + shift, header=order[k] in stacks) for k in range(pos, block_end)]
    del rows[pos:block_end]
    at = end - len(block) if pos < end else end
    rows[at:at] = block
    # the key field IS the display order, so renumber the run after the splice
    rows = [with_key(raw, key) for key, raw in enumerate(rows)]

    track_owner = bound_channels(data).get(track_object)
    replace = dict(zip(run, rows, strict=True))
    out = []
    for index, record in enumerate(records):
        raw = replace.get(index, record.raw)
        if object_id_of(record) == track_object and not summing:
            raw = set_parent(raw, stack_object)
        elif (not summing and record.tag == CHANNEL_TAG and record.key == NO_KEY
                and record.owner == track_owner):
            raw = set_stack_index(raw, stack.index)
        out.append(raw)

    result = sync_region_tracks(reassemble(data, out), track_count)
    if routed:
        result = to_summing_bus(result, {track_object: stack})
    result = select_track(result, track_object, track_count)
    require_valid(result)
    return result


def _header_above(depths: list[int], pos: int, depth: int) -> int:
    """The nearest row above ``pos`` shallower than ``depth``: the header enclosing it."""
    start = pos
    while start > 0 and depths[start] >= depth:
        start -= 1
    if depths[start] >= depth:
        raise ValueError(f"row {pos} sits at depth {depth} with no header above it")
    return start


def move_out_of_stack(data: bytes, track_object: int, track_count: int | None = None) -> bytes:
    """Move a member row one level out, right after the stack it leaves, the way Logic's drag
    does: depth byte down by one, the parent pointer and the channel's stack index now the
    enclosing stack's (cleared at the top level; a summing stack gives its members no index), the
    row selected. A row that lands as a direct member of a summing stack outputs to its bus
    (`stack-out-of-folder-after-logic`, `stack-out-of-inner-summing-after-logic`); at the top
    level its routing stays, out of a summing stack too. A row two levels deep takes two moves
    to reach the top."""
    require_full_walk(data)
    records = list(project_records(data))
    run = arrange_run(records, track_count)
    order = [row_object(records[i].raw) for i in run]
    if track_object not in order:
        raise ValueError(f"track object {track_object} is not in the arrange list")
    pos = order.index(track_object)
    depths = [records[i].raw[HEADER + MEMBER_AT] for i in run]
    depth = depths[pos]
    if depth == 0:
        return data                                       # already top level
    stacks = read_stacks(data, track_count)
    headers = {s.object_id for s in stacks}
    start = _header_above(depths, pos, depth)
    end = span_end(depths, start)
    block_end = span_end(depths, pos)                     # a moving stack takes its members along
    rows = [records[i].raw for i in run]
    block = [with_member(rows[k], depths[k] - 1, header=order[k] in headers) for k in range(pos, block_end)]
    del rows[pos:block_end]
    rows[end - len(block):end - len(block)] = block       # right after the stack it leaves
    rows = [with_key(raw, key) for key, raw in enumerate(rows)]
    outer = None                                          # the stack the row lands in, if any
    if depth > 1:
        outer_object = order[_header_above(depths, start, depth - 1)]
        outer = next((s for s in stacks if s.object_id == outer_object), None)
        if outer is None:
            raise ValueError(f"object {outer_object} encloses the row but is not a stack")
    routed = outer is not None and outer.kind == SUMMING
    if routed and summing_bus(data, outer) is None:
        raise ValueError(f"{outer.name!r} is fed from no bus, so a track moved into it has nowhere to go")

    track_owner = bound_channels(data).get(track_object)
    replace = dict(zip(run, rows, strict=True))
    out = []
    for index, record in enumerate(records):
        raw = replace.get(index, record.raw)
        if object_id_of(record) == track_object:
            raw = set_parent(raw, outer.object_id if outer else 0)
        elif (record.tag == CHANNEL_TAG and record.key == NO_KEY
                and record.owner == track_owner and len(raw) - HEADER > 200):
            raw = set_stack_index(raw, outer.index if outer and outer.kind == FOLDER else 0)
        out.append(raw)
    result = sync_region_tracks(reassemble(data, out), track_count)
    if routed:
        result = to_summing_bus(result, {track_object: outer})
    result = select_track(result, track_object, track_count)
    require_valid(result)
    return result


def flatten_stack(data: bytes, stack_object: int, track_count: int | None = None) -> bytes:
    """Flatten a stack as Logic's own Flatten Stack leaves the file (`stack-folder-flattened-logic`,
    `stack-summing-flattened-logic`, `nest-flatten-after-logic`): the header's arrange row goes and
    its members come up a level, their parent pointer cleared even inside another stack, and all
    of them selected, the first foremost. The header object, its strip, its flat row and the members'
    channel stack indices stay as they were, and so does every member's routing."""
    require_full_walk(data)
    records = list(project_records(data))
    run = arrange_run(records, track_count)
    order = [row_object(records[i].raw) for i in run]
    listed = read_stacks(data, track_count)
    stacks = {s.object_id: s for s in listed}
    if stack_object not in stacks:
        raise ValueError(f"object {stack_object} is not a stack")
    stack = stacks[stack_object]
    depths = [records[i].raw[HEADER + MEMBER_AT] for i in run]
    start = order.index(stack_object)
    end = span_end(depths, start)
    direct = [order[k] for k in range(start + 1, end) if depths[k] == stack.depth + 1]
    if not direct:
        raise ValueError("no track sits in it, so there is nothing to flatten")
    rows = [records[i].raw for i in run]
    kept = (rows[:start]
            + [with_member(rows[k], depths[k] - 1, header=order[k] in stacks) for k in range(start + 1, end)]
            + rows[end:])
    kept = [with_key(raw, key) for key, raw in enumerate(kept)]

    out = []
    for index, record in enumerate(records):
        if index in run:
            if index == run[0]:
                out += kept
            continue
        raw = record.raw
        if object_id_of(record) in direct:
            raw = set_parent(raw, 0)
        out.append(raw)
    count = None if track_count is None else track_count - 1
    result = sync_region_tracks(sync_row_count(reassemble(data, out), count), count)
    result = select_track(result, direct[0], count)
    if len(direct) > 1:                                   # Logic leaves every member selected
        result = reassemble(result, [set_selected_object(r.raw, True) if object_id_of(r) in direct else r.raw
                                     for r in project_records(result)])
    require_valid(result)
    return result
