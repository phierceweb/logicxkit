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
    set_parent,
)
from .insert import CHANNEL_TAG, HEADER, NO_KEY, project_records, reassemble
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


@dataclass
class Stack:
    name: str
    object_id: int
    track_key: int
    index: int = 0                 # the Sub number; +110 on every member channel
    owner: int | None = None       # the Sub N strip — where the stack's fader lives
    kind: str = FOLDER
    members: list[tuple[int, str]] = field(default_factory=list)


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
                    "member": payload[MEMBER_AT] == 1,
                    "expanded": bool(payload[EXPANDED_AT] & EXPANDED_BIT),
                    "grouping": obj.kind == GROUPING if obj else False,
                    "owner": owner, "label": chan.label if chan else None,
                    "stack_index": chan.stack_index if chan else 0})
    return out


def _is_stack(row: dict) -> bool:
    return row["grouping"] and (row["label"] or "").startswith(_SUB)


def read_stacks(data: bytes, track_count: int | None = None) -> list[Stack]:
    """Stacks in the arrange list, each with the tracks it holds.

    A stack is a grouping object bound to a ``Sub N`` strip; its members are the rows that
    follow it while their ``+14`` byte is set. Position still orders them — a member row
    always sits below its header — but the byte is what says it belongs.
    """
    stacks: list[Stack] = []
    open_stack: Stack | None = None
    for row in read_tracks(data, track_count):
        if _is_stack(row):
            open_stack = Stack(name=row["name"], object_id=row["object_id"],
                               track_key=row["key"], index=int(row["label"][len(_SUB):]),
                               owner=row["owner"])
            stacks.append(open_stack)
        elif open_stack is not None and not row["member"]:
            open_stack = None
        elif open_stack is not None and row["name"]:
            open_stack.members.append((row["key"], row["name"]))
    return stacks


def stack_parents(data: bytes) -> dict[int, int]:
    """track object id -> the stack object id it was explicitly dragged into (``ivnE+38``)."""
    return {i: o.parent for i, o in channel_objects(data).items() if o.parent}


def move_to_stack(data: bytes, track_object: int, stack_object: int,
                  track_count: int | None = None) -> bytes:
    """Move a track into a stack the way Logic does — from the top level or from another
    stack (both measured on Logic's own drags, 2026-09-04): reposition the row as the last
    member, set its member byte, stamp the parent pointer, set the stack index on the
    track's mixer channel, and leave the track selected. Refuses an invalid result."""
    require_full_walk(data)
    records = list(project_records(data))
    run = arrange_run(records, track_count)
    order = [row_object(records[i].raw) for i in run]
    if track_object not in order:
        raise ValueError(f"track object {track_object} is not in the arrange list")
    stacks = {s.object_id: s for s in read_stacks(data, track_count)}
    if stack_object not in stacks:
        raise ValueError(f"object {stack_object} is not a stack")
    if track_object in stacks:
        raise ValueError("moving a stack into a stack is not decoded")
    stack = stacks[stack_object]

    start = order.index(stack_object)
    end = start + 1
    while end < len(order) and records[run[end]].raw[HEADER + MEMBER_AT] == 1:
        end += 1
    if start < order.index(track_object) < end:
        return data                                   # already in this stack

    rows = [records[i].raw for i in run]
    moving = with_member(rows.pop(order.index(track_object)), 1)
    at = end - 1 if order.index(track_object) < end else end
    rows.insert(at, moving)
    # the key field IS the display order, so renumber the run after the splice
    rows = [with_key(raw, key) for key, raw in enumerate(rows)]

    track_owner = bound_channels(data).get(track_object)
    replace = dict(zip(run, rows, strict=True))
    out = []
    for index, record in enumerate(records):
        raw = replace.get(index, record.raw)
        if record.tag == ENV_TAG and len(raw) - HEADER > PARENT_AT + 4:
            payload = raw[HEADER:]
            if (struct.unpack_from("<I", payload, 0)[0] & 0xFFFF == CHANNEL_OBJECT.get(record.ver)
                    and struct.unpack_from("<I", payload, OBJECT_ID_AT)[0] == track_object):
                raw = set_parent(raw, stack_object)
        elif (record.tag == CHANNEL_TAG and record.key == NO_KEY
                and record.owner == track_owner):
            raw = set_stack_index(raw, stack.index)
        out.append(raw)

    result = sync_region_tracks(reassemble(data, out), track_count)
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


def move_out_of_stack(data: bytes, track_object: int, track_count: int | None = None) -> bytes:
    """Move a member row out to the top level, right after its stack, the way Logic's drag
    does (measured 2026-09-04): member byte cleared, parent pointer cleared, the channel's
    stack index cleared, the row selected."""
    require_full_walk(data)
    records = list(project_records(data))
    run = arrange_run(records, track_count)
    order = [row_object(records[i].raw) for i in run]
    if track_object not in order:
        raise ValueError(f"track object {track_object} is not in the arrange list")
    pos = order.index(track_object)
    if records[run[pos]].raw[HEADER + MEMBER_AT] != 1:
        return data                                       # already top level
    start = pos
    while start > 0 and records[run[start]].raw[HEADER + MEMBER_AT] == 1:
        start -= 1
    end = pos
    while end + 1 < len(order) and records[run[end + 1]].raw[HEADER + MEMBER_AT] == 1:
        end += 1
    rows = [records[i].raw for i in run]
    moving = with_member(rows.pop(pos), 0)
    rows.insert(end, moving)                              # end shifted down by one after the pop
    rows = [with_key(raw, key) for key, raw in enumerate(rows)]

    track_owner = bound_channels(data).get(track_object)
    replace = dict(zip(run, rows, strict=True))
    out = []
    for index, record in enumerate(records):
        raw = replace.get(index, record.raw)
        if record.tag == ENV_TAG and len(raw) - HEADER > PARENT_AT + 4:
            payload = raw[HEADER:]
            if (struct.unpack_from("<I", payload, 0)[0] & 0xFFFF == CHANNEL_OBJECT.get(record.ver)
                    and struct.unpack_from("<I", payload, OBJECT_ID_AT)[0] == track_object):
                raw = set_parent(raw, 0)
        elif (record.tag == CHANNEL_TAG and record.key == NO_KEY
                and record.owner == track_owner and len(raw) - HEADER > 200):
            raw = set_stack_index(raw, 0)
        out.append(raw)
    result = sync_region_tracks(reassemble(data, out), track_count)
    result = select_track(result, track_object, track_count)
    require_valid(result)
    return result
