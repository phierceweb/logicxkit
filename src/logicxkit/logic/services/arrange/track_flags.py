"""One arrange row's power and hidden bits."""

from __future__ import annotations

from ..stream.stream import project_records, reassemble
from .tracklist import arrange_run, row_object, with_hidden, with_power
from ..stream.validate import require_full_walk, require_valid


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
