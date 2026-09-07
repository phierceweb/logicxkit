"""Region placement: the song container's entries name a track by object id and 1-based
arrange row; the writers that move rows renumber them."""

import struct
import unittest

from _records import env_obj, marker, proj, rec, track
from logicxkit.logic.services.insert import project_records
from logicxkit.logic.services.regions import (
    ENTRY, ROW_COUNT_FROM_END, ROW_UNIT, TAIL, placements, region_errors, row_count_errors,
    sync_region_tracks, sync_row_count,
)
from logicxkit.logic.services.reorder import move_track

TAIL_BYTES = bytes.fromhex("f1000000ffffff3f") + bytes(8)


def entry(object_id: int, row: int, slot: int = 64) -> bytes:
    p = bytearray(ENTRY)
    struct.pack_into("<I", p, 0, 0x20)
    struct.pack_into("<H", p, 16, object_id)
    struct.pack_into("<H", p, 20, row)
    struct.pack_into("<I", p, 32, slot)
    return bytes(p)


def song(rows: list[bytes], entries: list[bytes], count: int | None = None) -> list[bytes]:
    """The arrange rows inside their container (its row count ``count``, default right),
    then the flat list of the same objects plus one."""
    head = bytearray(345)
    struct.pack_into("<I", head, 8, 226)
    struct.pack_into("<I", head, len(head) - ROW_COUNT_FROM_END, ROW_UNIT * (len(rows) if count is None else count))
    return ([rec(b"qeSM", 0xFFFF, 0xFFFF, bytes(head), 5)] + rows + [marker(),
            rec(b"qSvE", 226, 0xFFFF, b"".join(entries) + TAIL_BYTES, 5)])


def flat(*object_ids: int) -> list[bytes]:
    return [marker()] + [track(k, oid) for k, oid in enumerate(object_ids)] + [marker()]


COUNT = 3                       # NumberOfTracks: one less than the arrange rows, as Logic keeps it


class PlacementTest(unittest.TestCase):
    def setUp(self):
        rows = [track(0, 88), track(1, 144), track(2, 120), track(3, 80, flag=3)]
        self.data = proj(env_obj(88, "Kick"), env_obj(144, "Click"), env_obj(120, "Guitar 2"),
                         env_obj(80, "Master", grouping=True),
                         *song(rows, [entry(144, 2), entry(120, 3), entry(9999, 7)]),
                         *flat(88, 144, 120, 80, 500))

    def test_placements_name_the_track_rows_and_skip_other_entries(self):
        self.assertEqual([(oid, row) for _o, oid, row in placements(project_records(self.data), COUNT)],
                         [(144, 2), (120, 3)])
        self.assertEqual(region_errors(self.data, COUNT), [])

    def test_a_stale_row_is_an_error_and_sync_fixes_it(self):
        rows = [track(0, 88), track(1, 500), track(2, 144), track(3, 120), track(4, 80, flag=3)]
        data = proj(*song(rows, [entry(144, 2), entry(120, 3)]), *flat(88, 500, 144, 120, 80))
        self.assertEqual(region_errors(data, 4), ["object 144: placed on row 2, sits on row 3",
                                                  "object 120: placed on row 3, sits on row 4"])
        fixed = sync_region_tracks(data, 4)
        self.assertEqual(region_errors(fixed, 4), [])
        self.assertEqual(len(fixed), len(data))
        self.assertEqual(sync_region_tracks(fixed, 4), fixed)

    def test_an_object_with_two_rows_counts_its_first(self):
        rows = [track(0, 88), track(1, 120), track(2, 120, flag=5), track(3, 80, flag=3)]
        data = proj(*song(rows, [entry(120, 2)]), *flat(88, 120, 80, 500))
        self.assertEqual(region_errors(data, COUNT), [])

    def test_without_a_container_sync_leaves_the_project_alone(self):
        data = proj(track(0, 88), track(1, 120), marker(), *flat(88, 120, 500))
        self.assertEqual(sync_region_tracks(data, 1), data)
        self.assertEqual(region_errors(data, 1), [])

    def test_reorder_renumbers_the_placements(self):
        moved = move_track(self.data, 120, before=88, track_count=COUNT)
        self.assertEqual(region_errors(moved, COUNT), [])
        self.assertEqual([(oid, row) for _o, oid, row in placements(project_records(moved), COUNT)],
                         [(144, 3), (120, 1)])


class RowCountTest(unittest.TestCase):
    def test_a_stale_count_is_an_error_and_sync_sets_it(self):
        rows = [track(0, 88), track(1, 120), track(2, 80, flag=3)]
        data = proj(*song(rows, [], count=2), *flat(88, 120, 80, 500))
        self.assertEqual(row_count_errors(data, 2), ["song container says 2 rows, the list holds 3"])
        fixed = sync_row_count(data, 2)
        self.assertEqual(row_count_errors(fixed, 2), [])
        self.assertEqual(len(fixed), len(data))
        self.assertEqual(sync_row_count(fixed, 2), fixed)

    def test_row_count_reads_the_container(self):
        from logicxkit.logic.services.regions import row_count, song_container
        from logicxkit.logic.services.insert import project_records
        from logicxkit.logic.services.tracklist import arrange_run
        data = proj(*song([track(0, 88), track(1, 80, flag=3)], []), *flat(88, 80, 500))
        recs = project_records(data)
        self.assertEqual(row_count(recs, song_container(recs, arrange_run(recs, 1))), 2)


class TailTest(unittest.TestCase):
    def test_the_tail_is_never_read_as_an_entry(self):
        data = proj(*song([track(0, 88), track(1, 80, flag=3)], []), *flat(88, 80, 500))
        self.assertEqual(placements(project_records(data), 1), [])
        self.assertEqual(TAIL, len(TAIL_BYTES))


if __name__ == "__main__":
    unittest.main()
