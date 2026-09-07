"""What every Logic-written file on hand obeys, measured per file so a writer's output can be
held to the same standard without a byte-for-byte golden."""

import struct

from logicxkit.logic.services.binding import bound_channels
from logicxkit.logic.services.channel_alloc import is_mixer_record
from logicxkit.logic.services.environment import channel_objects, name_end, object_record
from logicxkit.logic.services.groups import group_errors
from logicxkit.logic.services.insert import HEADER, project_records
from logicxkit.logic.services.regions import region_errors, row_count_errors
from logicxkit.logic.services.registry import slot_errors
from logicxkit.logic.services.sends import SEND_FLAG_AT
from logicxkit.logic.services.sequence import link_errors
from logicxkit.logic.services.tracklist import arrange_run, row_object
from logicxkit.logic.services.validate import validate_project


def report(data: bytes, track_count: int | None) -> dict:
    """validate / link_errors / object index / send flags / the three selection marks."""
    recs = project_records(data)
    owners = bound_channels(data)
    objs = channel_objects(data)
    bad_index = []
    for oid in objs:
        if oid not in owners:
            continue
        p = object_record(recs, oid)[HEADER:]
        if struct.unpack_from("<H", p, name_end(p))[0] != owners[oid] + 1:
            bad_index.append(oid)
    satellites: dict[int, set[int]] = {}
    for r in recs:
        if r.tag == b"UCuA":
            satellites.setdefault(r.owner, set()).add(r.key)
    bad_flags = []
    for r in recs:
        if is_mixer_record(r) and len(r.raw) - HEADER > SEND_FLAG_AT + 12:
            keys = satellites.get(r.owner, set())                  # a slot under a send key counts too
            flags = [struct.unpack_from("<I", r.raw, HEADER + SEND_FLAG_AT + 4 * k)[0] == 1 for k in range(3)]
            if any(flags[k] != (k in keys) for k in range(3)):
                bad_flags.append(r.owner)
    run = arrange_run(recs, track_count)
    g = next(r.raw[HEADER:] for r in recs if r.tag == b"gnoS")
    return {
        "validate": validate_project(data),
        "link_errors": len(link_errors(recs)),
        "bad_object_index": bad_index,
        "bad_send_flags": bad_flags,
        "bad_region_tracks": region_errors(data, track_count),
        "bad_row_count": row_count_errors(data, track_count),
        "bad_slot_entries": slot_errors(data),
        "bad_groups": group_errors(data),
        "selected_objects": [oid for oid in objs if object_record(recs, oid)[HEADER + 80] == 1],
        "selected_rows": [row_object(recs[i].raw) for i in run if recs[i].raw[HEADER + 43] == 0x40],
        "gnos_selected": struct.unpack_from("<I", g, 94)[0],
    }


def assert_consistent(test, data: bytes, track_count: int, *, selected: int, link_errors_before: int):
    r = report(data, track_count)
    test.assertEqual(r["validate"], [])
    test.assertEqual(r["link_errors"], link_errors_before)
    test.assertEqual(r["bad_object_index"], [])
    test.assertEqual(r["bad_send_flags"], [])
    test.assertEqual(r["bad_region_tracks"], [])
    test.assertEqual(r["bad_row_count"], [])
    test.assertEqual(r["bad_slot_entries"], [])
    test.assertEqual(r["bad_groups"], [])
    test.assertEqual((r["selected_objects"], r["selected_rows"], r["gnos_selected"]),
                     ([selected], [selected], selected))
