"""Move an arrange row. Measured on a real drag (Ride above Hi Hat inside Drums, 2026-09-01):
Logic renumbers the two rows' keys, selects the moved row and touches nothing else — no index
tables move. So a move within one parent is a splice, a renumber and a select.

Moving a row INTO a stack is `stacks.move_to_stack`; moving one OUT of a stack has not been
observed and is refused.
"""

from __future__ import annotations

from .insert import project_records, reassemble
from .recbuild import with_key
from .regions import sync_region_tracks
from .selection import select_track
from .stacks import MEMBER_AT, read_stacks, read_tracks
from .tracklist import arrange_run, row_object
from .validate import require_full_walk, require_valid


def _parent_of(rows: list[dict], key: int) -> int | None:
    """Object id of the stack header above ``key``, or None for a top-level row."""
    for row in reversed(rows[:key + 1]):
        if row["key"] == key and not row["member"]:
            return None
        if row["grouping"] and (row["label"] or "").startswith("Sub "):
            return row["object_id"]
    return None


def move_track(data: bytes, track_object: int, *, before: int | None = None,
               after: int | None = None, track_count: int | None = None) -> bytes:
    """Put ``track_object``'s row immediately before or after another row's, same parent."""
    if (before is None) == (after is None):
        raise ValueError("give exactly one of before= / after=")
    require_full_walk(data)
    target = before if before is not None else after
    rows = read_tracks(data, track_count)
    by_obj = {r["object_id"]: r for r in rows}
    if track_object not in by_obj or target not in by_obj:
        raise ValueError("track or target is not in the arrange list")
    if by_obj[track_object]["grouping"] and (by_obj[track_object]["label"] or "").startswith("Sub "):
        raise ValueError("moving a stack header is not supported")
    src_parent = _parent_of(rows, by_obj[track_object]["key"])
    dst_parent = _parent_of(rows, by_obj[target]["key"])
    if src_parent != dst_parent:
        raise ValueError("track and target sit under different parents; use move_to_stack "
                         "to move into a stack (moving out of one is not decoded)")

    records = list(project_records(data))
    run = arrange_run(records, track_count)
    order = [row_object(records[i].raw) for i in run]
    raws = [records[i].raw for i in run]
    moving = raws.pop(order.index(track_object))
    order.remove(track_object)
    at = order.index(target) + (0 if before is not None else 1)
    raws.insert(at, moving)
    raws = [with_key(raw, key) for key, raw in enumerate(raws)]
    replace = dict(zip(run, raws, strict=True))
    result = reassemble(data, [replace.get(i, r.raw) for i, r in enumerate(records)])
    result = sync_region_tracks(result, track_count)
    result = select_track(result, track_object, track_count)
    require_valid(result)
    return result


__all__ = ["MEMBER_AT", "move_track", "read_stacks"]
