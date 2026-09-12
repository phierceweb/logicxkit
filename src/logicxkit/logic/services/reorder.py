"""Move an arrange row. Logic's own drag renumbers the two rows' keys, selects the moved row and
touches nothing else, so a move within one parent is a splice, a renumber and a select; a stack
header moves with its member rows as one block. Moving a row into a stack is
`stacks.move_to_stack`; a move across parents is refused."""

from __future__ import annotations

from .insert import HEADER, project_records, reassemble
from .recbuild import with_key
from .regions import sync_region_tracks
from .selection import select_track
from .stacks import MEMBER_AT, read_stacks, read_tracks
from .tracklist import arrange_run, row_object
from .validate import require_full_walk, require_valid


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
    stacks = read_stacks(data, track_count)
    headers = {s.object_id for s in stacks}
    parent = {key: s.object_id for s in stacks for key, _name in s.members}
    src_parent = parent.get(by_obj[track_object]["key"])
    dst_parent = parent.get(by_obj[target]["key"])
    if src_parent != dst_parent:
        raise ValueError("track and target sit under different parents; use move_to_stack "
                         "to move into a stack (moving out of one is not decoded)")

    records = list(project_records(data))
    run = arrange_run(records, track_count)
    order = [row_object(records[i].raw) for i in run]
    raws = [records[i].raw for i in run]

    def block(obj: int) -> slice:
        """A header's row and the member rows under it; a plain row alone (Logic's own drag of
        a stack header moved header and member as one block, 2026-09-12)."""
        start = order.index(obj)
        end = start + 1
        if obj in headers:
            while end < len(raws) and raws[end][HEADER + MEMBER_AT] == 1:
                end += 1
        return slice(start, end)

    src = block(track_object)
    moving, moving_ids = raws[src], order[src]
    del raws[src], order[src]
    dst = block(target)
    at = dst.start if before is not None else dst.stop
    raws[at:at] = moving
    order[at:at] = moving_ids
    raws = [with_key(raw, key) for key, raw in enumerate(raws)]
    replace = dict(zip(run, raws, strict=True))
    result = reassemble(data, [replace.get(i, r.raw) for i, r in enumerate(records)])
    result = sync_region_tracks(result, track_count)
    if track_object not in headers:      # a dragged header keeps the selection it had (Logic's save)
        result = select_track(result, track_object, track_count)
    require_valid(result)
    return result


__all__ = ["MEMBER_AT", "move_track", "read_stacks"]
