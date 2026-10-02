"""Track stacks — the arrange track list, and the folder stacks that group it.

Three record types cooperate, and none of them is self-describing:

* ``karT`` — the track list. Runs are separated by zero-size marker records; the run holding
  ``NumberOfTracks + 1`` entries is the arrange list, and each record's ``key`` is its display
  position. 58 bytes at Logic 12, 57 at Logic 11.
* ``ivnE`` — the Environment objects. ``+16`` is an object id in the same space as ``karT+8``,
  ``+158`` a u16-length-prefixed name, and ``+154`` the kind byte.
* ``OCuA`` — the mixer channel, holding fader/pan and the plugin slots. It is bound to its
  object by the object's UUID (``binding.py``); a folder stack's strip is ``Sub N``, and every
  member channel carries N at ``+110``.

FOLDER vs SUMMING. Logic has both, and they differ in what they can hold:

* A **folder stack** groups tracks that keep their own outputs. Its strip carries only pan,
  volume and mute/solo — Logic hosts no inserts on it, so "add an effect to the stack" has to
  mean the bus its members feed.
* A **summing stack** owns a real aux: its members output to it, and it takes inserts like any
  channel.

Every stack in the sessions here is a folder stack, confirmed by the user and by the file: each
binds to a ``Sub`` strip. ``Stack.kind`` records which one a stack is so summing support can be
added without reinterpreting anything already written.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from .binding import bound_channels, channels, set_stack_index
from .environment import (  # noqa: F401 — re-exported for callers and tests
    CHANNEL_OBJECT,
    ENV_TAG,
    GROUPING,
    KIND_AT,
    NAME_AT,
    OBJECT_ID_AT,
    PARENT_AT,
    channel_objects,
    object_id_of,
    set_parent,
)
from .mixer import CHANNEL_TAG
from .stream import HEADER, NO_KEY, project_records, reassemble
from .recbuild import with_key
from .regions import sync_region_tracks
from .selection import select_track
from .tracklist import (  # noqa: F401 — re-exported for callers and tests
    EXPANDED_AT,
    EXPANDED_BIT,
    HIDDEN_BIT,
    HIDDEN_FLAG,
    MEMBER_AT,
    OFF_BIT,
    TRACK_FLAG_AT,
    TRACK_OBJECT_AT,
    TRACK_TAG,
    arrange_run,
    row_object,
    track_runs,
    with_hidden,
    with_member,
    with_power,
)
from .validate import require_full_walk, require_valid

FOLDER = "folder"
SUMMING = "summing"
_SUB = "Sub "
_AUX = "Aux "                 # a summing stack's header is bound to an Aux strip


@dataclass
class Stack:
    name: str
    object_id: int
    track_key: int
    index: int = 0                 # the Sub number (+110 on every member channel); a summing stack's Aux number
    owner: int | None = None       # the Sub N or Aux N strip — where the stack's fader lives
    kind: str = FOLDER
    members: list[tuple[int, str]] = field(default_factory=list)
    depth: int = 0                 # 0 at the top level; the row's +14 byte
    parent: int | None = None      # the enclosing stack's object id

    @property
    def strip(self) -> str:
        return f"{'Aux' if self.kind == SUMMING else 'Sub'} {self.index}"


def track_lists(data: bytes) -> list[list]:
    """``karT`` records split on the zero-size markers that delimit each list."""
    records = project_records(data)
    return [[records[i] for i in run] for run in track_runs(records)]


def arrange_list(data: bytes, track_count: int | None = None) -> list:
    """The run that is the arrange window's track list, longest-run fallback.

    A project holds several track lists (other windows keep their own); the arrange one has an
    entry per track plus a terminator, so the count picks it out when it is known.
    """
    records = project_records(data)
    try:
        return [records[i] for i in arrange_run(records, track_count)]
    except ValueError:
        return []


def read_tracks(data: bytes, track_count: int | None = None) -> list[dict]:
    """The arrange list in display order.

    Each row: ``key, object_id, name, flag, hidden, member, expanded, grouping, owner, label,
    stack_index`` — the last three from the mixer channel the row's object is bound to
    (``None``/0 if none). ``member`` is the row's own +14 byte, the field that says it sits
    inside the stack above it.
    """
    objs = channel_objects(data)
    owners = bound_channels(data)
    chans = channels(data)
    out = []
    for record in arrange_list(data, track_count):
        payload = record.raw[HEADER:]
        oid = struct.unpack_from("<I", payload, TRACK_OBJECT_AT)[0]
        flag = struct.unpack_from("<I", payload, TRACK_FLAG_AT)[0]
        obj = objs.get(oid)
        owner = owners.get(oid)
        chan = chans.get(owner) if owner is not None else None
        out.append({"key": record.key, "object_id": oid, "name": obj.name if obj else None,
                    "colour": obj.colour if obj else None,
                    "icon": obj.icon if obj else None,
                    "flag": flag, "hidden": bool(flag & HIDDEN_BIT), "on": not flag & OFF_BIT,
                    "member": payload[MEMBER_AT] != 0, "depth": payload[MEMBER_AT],
                    "expanded": bool(payload[EXPANDED_AT] & EXPANDED_BIT),
                    "grouping": obj.kind == GROUPING if obj else False,
                    "owner": owner, "label": chan.label if chan else None,
                    "stack_index": chan.stack_index if chan else 0})
    return out


def _stack_kind(row: dict, following: dict | None) -> str | None:
    """folder for a grouping row bound to a Sub strip; summing for one bound to an Aux whose
    next row sits one level under it — the grouping flag alone is set on plain aux, instrument
    and output tracks too, and an aux inside a folder stack is followed by its sibling (Logic's
    own Create Track Stack of each kind on a blank project, 2026-09-12, against a template with
    three grouping aux tracks that are not stacks); else None."""
    if not row["grouping"]:
        return None
    label = row["label"] or ""
    if label.startswith(_SUB):
        return FOLDER
    if label.startswith(_AUX) and following is not None and following["depth"] > row["depth"]:
        return SUMMING
    return None


def _is_stack(row: dict, following: dict | None = None) -> bool:
    return _stack_kind(row, following) is not None


def read_stacks(data: bytes, track_count: int | None = None) -> list[Stack]:
    """Stacks in the arrange list, each with the tracks it holds.

    A stack is a grouping object bound to a ``Sub N`` strip (folder) or an ``Aux N`` strip
    (summing); its members are the rows that follow it while their ``+14`` byte is set. The byte
    is the nesting depth: a header at depth d
    holds the rows after it at depth d+1, a nested header among them. Position still orders
    them — a member row always sits below its header — but the byte is what says it belongs.
    """
    stacks: list[Stack] = []
    open_: list[Stack] = []                           # the headers enclosing the current row, by depth
    rows = read_tracks(data, track_count)
    for i, row in enumerate(rows):
        depth = row["depth"]
        del open_[depth:]                             # a row at depth d closes every header at d or deeper
        following = rows[i + 1] if i + 1 < len(rows) else None
        if _is_stack(row, following):
            kind = _stack_kind(row, following)
            nested = bool(open_) and depth == len(open_)      # a depth jump belongs to nothing
            stack = Stack(name=row["name"], object_id=row["object_id"],
                          track_key=row["key"], index=int(row["label"].split()[1]),
                          owner=row["owner"], kind=kind, depth=depth,
                          parent=open_[-1].object_id if nested else None)
            if nested:
                open_[-1].members.append((row["key"], row["name"]))
            stacks.append(stack)
            if depth == len(open_):
                open_.append(stack)
        elif open_ and depth == len(open_) and row["name"]:
            open_[-1].members.append((row["key"], row["name"]))
    return stacks


def rows_below(stacks: list[Stack], stack: Stack, *, headers: bool = True) -> list[tuple[int, str]]:
    """Every (key, name) under ``stack``, nested stacks' rows included; their headers too unless
    ``headers`` is False. ``Stack.members`` alone is the direct children."""
    inner = {s.track_key: s for s in stacks if s.parent == stack.object_id}
    out = []
    for key, name in stack.members:
        if key in inner:
            if headers:
                out.append((key, name))
            out += rows_below(stacks, inner[key], headers=headers)
        else:
            out.append((key, name))
    return out


def enclosing(stacks: list[Stack], key: int) -> list[Stack]:
    """The stacks around the arrange row ``key``, nearest first."""
    holder = {k: s for s in stacks for k, _name in s.members}
    out: list[Stack] = []
    s = holder.get(key)
    while s is not None and s not in out:
        out.append(s)
        s = holder.get(s.track_key)
    return out


def summing_around(stacks: list[Stack], key: int) -> Stack | None:
    return next((s for s in enclosing(stacks, key) if s.kind == SUMMING), None)


def span_end(depths: list[int], start: int) -> int:
    """The index after the last row a header at ``start`` holds: every following row deeper than it."""
    end = start + 1
    while end < len(depths) and depths[end] > depths[start]:
        end += 1
    return end


def stack_parents(data: bytes) -> dict[int, int]:
    """track object id -> the stack object id it was explicitly dragged into (``ivnE+38``)."""
    return {i: o.parent for i, o in channel_objects(data).items() if o.parent}


def move_to_stack(data: bytes, track_object: int, stack_object: int,
                  track_count: int | None = None) -> bytes:
    """Move a track into a stack the way Logic does — from the top level or from another
    stack (both measured on Logic's own drags, 2026-09-04): reposition the row as the last
    member, set its member byte, stamp the parent pointer, set the stack index on the
    track's mixer channel, and leave the track selected. Into a summing stack its parent and
    stack index stay (`stack-summing-dragged-in-logic`); a track entering one, directly or
    through a folder inside it, outputs to its bus (`stack_place`). Refuses an invalid result."""
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
    from .stack_place import summing_bus, to_summing_bus
    listed = list(stacks.values())
    entering = stack if summing else summing_around(listed, stack.track_key)
    if entering is not None and track_object in stacks:
        raise ValueError("a stack moved into a summing stack is not written: where its members "
                         "route then has not been measured")
    was = summing_around(listed, order.index(track_object))
    routed = entering is not None and (was is None or was.object_id != entering.object_id)
    if routed and summing_bus(data, entering) is None:
        raise ValueError(f"{entering.name!r} is fed from no bus, so a track moved into it has nowhere to go")

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
        result = to_summing_bus(result, {track_object: entering})
    result = select_track(result, track_object, track_count)
    require_valid(result)
    return result



def set_power(data: bytes, track_object: int, on: bool, track_count: int | None = None) -> bytes:
    """Switch one track on or off — the row bit Logic's own save flipped for that click."""
    require_full_walk(data)
    records = project_records(data)
    run = arrange_run(records, track_count)
    rows = {i for i in run if row_object(records[i].raw) == track_object}
    if not rows:
        raise ValueError(f"track object {track_object} is not in the arrange list")
    result = reassemble(data, [with_power(r.raw, on) if i in rows else r.raw for i, r in enumerate(records)])
    require_valid(result)
    return result


def set_hidden(data: bytes, track_object: int, hidden: bool, track_count: int | None = None) -> bytes:
    """Hide or show one arrange row. The bit is decoded from reads only; no Logic hide save
    has been measured."""
    require_full_walk(data)
    records = project_records(data)
    run = arrange_run(records, track_count)
    rows = {i for i in run if row_object(records[i].raw) == track_object}
    if not rows:
        raise ValueError(f"track object {track_object} is not in the arrange list")
    result = reassemble(data, [with_hidden(r.raw, hidden) if i in rows else r.raw
                               for i, r in enumerate(records)])
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
    row selected. Its routing stays, out of a summing stack too. A row two levels deep takes two
    moves to reach the top."""
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

    track_owner = bound_channels(data).get(track_object)
    replace = dict(zip(run, rows, strict=True))
    out = []
    for index, record in enumerate(records):
        raw = replace.get(index, record.raw)
        if object_id_of(record) == track_object:
            raw = set_parent(raw, outer.object_id if outer else 0)
        elif (record.tag == CHANNEL_TAG and record.key == NO_KEY
                and record.owner == track_owner and len(raw) - HEADER > 200):
            if outer is None or outer.kind == FOLDER:
                raw = set_stack_index(raw, outer.index if outer else 0)
        out.append(raw)
    result = sync_region_tracks(reassemble(data, out), track_count)
    result = select_track(result, track_object, track_count)
    require_valid(result)
    return result
