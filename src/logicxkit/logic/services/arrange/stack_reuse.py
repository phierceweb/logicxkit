"""Members that are all a bus has: that bus's own aux made the summing stack's main track.

Logic 12.4's Create Track Stack… (Summing) over tracks that are the only channels on a bus
makes no aux (`stack-summing-reuse-logic`, `stack-summing-reuse-track-logic`): the aux already
fed from the bus is the main track. What changes:

* the arrange list: a header row for the aux's own object where the first member sat, expanded;
  the row the aux had elsewhere, when it had one, is gone (the header's is a fresh row either
  way); the members' rows go one level deeper
* the objects: the members take the aux's object as parent, and that object takes the
  members' colour: 16 from 5 and from 40 over tracks coloured 16
  (`stack-summing-reuse-colour-*`). Its kind byte stays what it was
* nothing else — no channel record, no routing, no sequence: an aux in use has its object and
  its index-table entry already

Measured at the top level, with the aux's own row at the top level and holding nothing. Any
other place is refused. `NumberOfTracks` in MetaData.plist is the caller's job: it grows only
when the aux had no row.
"""

from __future__ import annotations

from ..mixer.binding import bound_channels, channels, output_labels
from ..regions.regions import sync_region_tracks, sync_row_count
from ..stream.recbuild import with_key
from ..stream.sequence import index_table, table_entry
from ..stream.stream import HEADER, project_records, reassemble
from ..stream.validate import require_valid
from .environment import COLOUR_AT, channel_objects, object_id_of, set_parent
from .selection import select_track
from .stack_pattern import packaged_aux
from .tracklist import MEMBER_AT, arrange_run, new_row, row_object, with_member


def main_track_from_aux(data: bytes, *, bus: str, aux_owner: int, members: list[int], inside: int | None,
                        track_count: int | None = None) -> tuple[bytes, dict]:
    """The aux ``aux_owner``, fed from ``bus``, made the main track over ``members`` (track
    objects in arrange order, the only channels on that bus)."""
    records = project_records(data)
    label = channels(data)[aux_owner].label
    bound = [o for o, owner in bound_channels(data).items() if owner == aux_owner]
    if len(bound) != 1:
        raise ValueError(f"{label} is bound to {len(bound)} objects, not one")
    header = bound[0]
    entry = table_entry(records[index_table(records)].raw[HEADER:], header)
    if entry is None:
        raise ValueError(f"{label} has no sequence of its own: a track for it is not measured")
    run = arrange_run(records, track_count)
    if run != list(range(run[0], run[0] + len(run))):
        raise ValueError("the arrange list is not one run of records")
    rows = [records[i].raw for i in run]
    own = next((k for k, raw in enumerate(rows) if row_object(raw) == header), None)
    if inside is not None or header in members:
        raise ValueError(f"every member outputs to {bus}, which only they feed, and they sit inside a stack: "
                         f"what Logic makes of {label} there is not measured")
    if own is not None:
        heads = own + 1 < len(rows) and rows[own + 1][HEADER + MEMBER_AT] > rows[own][HEADER + MEMBER_AT]
        if rows[own][HEADER + MEMBER_AT] or heads:
            raise ValueError(f"every member outputs to {bus}, which only they feed, and {label}'s own track sits "
                             "inside a stack or heads one: where Logic's stack puts it is not measured")

    member_set = set(members)
    gone = member_set | {header}
    colour = channel_objects(data)[members[0]].colour
    head = new_row(rows[own] if own is not None else packaged_aux(records)["row"],
                   object_id=header, member=0, expanded=True)
    first = next(k for k, raw in enumerate(rows) if row_object(raw) == members[0])
    kept = [raw for raw in rows if row_object(raw) not in gone]
    at = sum(1 for raw in rows[:first] if row_object(raw) not in gone)
    listed = kept[:at] + [head] + [with_member(raw, 1) for raw in rows if row_object(raw) in member_set] + kept[at:]

    out, in_run = [], set(run)
    for i, r in enumerate(records):
        if i == run[0]:
            out += [with_key(raw, key) for key, raw in enumerate(listed)]
        if i in in_run:
            continue
        raw = r.raw
        if object_id_of(r) in member_set:
            raw = set_parent(raw, header)
        elif object_id_of(r) == header:
            buf = bytearray(raw)
            buf[HEADER + COLOUR_AT] = colour
            raw = bytes(buf)
        out.append(raw)

    added = int(own is None)
    count = None if track_count is None else track_count + added
    result = sync_row_count(reassemble(data, out), count)
    result = sync_region_tracks(result, count)
    result = select_track(result, header, count)
    require_valid(result)
    return result, {"object_id": header, "owner": aux_owner, "label": label, "sequence": entry[0], "slot": entry[1],
                    "input": bus, "bus": bus, "members": members, "output": output_labels(result).get(aux_owner),
                    "left": {}, "reused": True, "tracks_added": added, "name": channel_objects(result)[header].name}
