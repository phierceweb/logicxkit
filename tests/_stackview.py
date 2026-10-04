"""What the stack goldens compare between a written project and Logic's own save of the same
change: the rows, the stacks, every channel's use and routing, the mixer-order list, the index
table and the channel records."""

from __future__ import annotations

import _goldens

from logicxkit.logic.services.arrange.environment import channel_objects
from logicxkit.logic.services.arrange.stacks import read_stacks, read_tracks
from logicxkit.logic.services.arrange.tracklist import arrange_run, flat_run, row_object
from logicxkit.logic.services.mixer.binding import channels, input_labels, output_labels
from logicxkit.logic.services.mixer.mixer import is_mixer_record
from logicxkit.logic.services.project.project import project_metadata
from logicxkit.logic.services.stream.sequence import index_table, table_entries
from logicxkit.logic.services.stream.stream import HEADER, project_records
from logicxkit.logicx import project_data


def load(key: str) -> tuple[bytes, int]:
    bundle = _goldens.path(key)
    return project_data(bundle), project_metadata(bundle)["tracks"]


def obj(data: bytes, name: str) -> int:
    return next(i for i, o in channel_objects(data).items() if o.name == name)


def view(data: bytes, count: int) -> dict:
    """Rows, stacks, every channel's use, routing and stack index, the mixer-order list and
    each index-table entry's place in it."""
    records, objects, chans = project_records(data), channel_objects(data), channels(data)
    ins, outs = input_labels(data), output_labels(data)
    named = lambda o: objects[o].name if o in objects else None                  # noqa: E731
    return {"rows": [(r["name"], r["label"], r["depth"]) for r in read_tracks(data, count)],
            "stacks": [(s.name, s.kind, s.strip, s.depth, [n for _k, n in s.members]) for s in read_stacks(data, count)],
            "strips": {c.label: (c.in_use, c.stack_index, ins.get(o), outs.get(o)) for o, c in chans.items()},
            "flat": [named(row_object(records[i].raw)) for i in flat_run(records, arrange_run(records, count))],
            "table": sorted((named(e[1]) or "", e[2]) for e in table_entries(records[index_table(records)].raw[HEADER:]))}


def placed(data: bytes, count: int) -> dict:
    """`view` less what depends on where in its stack a dragged row was dropped."""
    seen = view(data, count)
    return {"rows": sorted((name, depth) for name, _label, depth in seen["rows"]),
            "stacks": sorted((name, kind, strip, depth, sorted(members)) for name, kind, strip, depth, members in seen["stacks"]),
            "strips": seen["strips"], "parents": parents(data)}


def parents(data: bytes) -> dict[str, str | None]:
    objects = channel_objects(data)
    return {o.name: objects[o.parent].name if o.parent in objects else None for o in objects.values()}


def channel_records(data: bytes, like: bytes | None = None) -> dict[int, bytes]:
    """owner -> channel record; with ``like``, each channel's own UUID told as ``like``'s."""
    found = {r.owner: r.raw[HEADER:] for r in project_records(data) if is_mixer_record(r)}
    if like is not None:
        mine, theirs = channels(data), channels(like)
        told = {mine[o].uuid: theirs[o].uuid for o in mine if o in theirs and mine[o].uuid != theirs[o].uuid}
        for owner, raw in found.items():
            for uuid, as_logic in told.items():
                raw = raw.replace(uuid, as_logic)
            found[owner] = raw
    return found
