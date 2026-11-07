"""Region placement: the song container's entries name a track by object id and 1-based
arrange row; the writers that move rows renumber them."""

import struct
import unittest

from _records import env_obj, marker, proj, rec, track
from logicxkit.logic.services.stream.stream import project_records
from logicxkit.logic.services.regions.regions import (
    ENTRY, ROW_COUNT_FROM_END, ROW_UNIT, TAIL, placements, region_errors, row_count_errors,
    sync_region_tracks, sync_row_count,
)
from logicxkit.logic.services.arrange.reorder import move_track

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
        from logicxkit.logic.services.regions.regions import row_count, song_container
        from logicxkit.logic.services.stream.stream import project_records
        from logicxkit.logic.services.arrange.tracklist import arrange_run
        data = proj(*song([track(0, 88), track(1, 80, flag=3)], []), *flat(88, 80, 500))
        recs = project_records(data)
        self.assertEqual(row_count(recs, song_container(recs, arrange_run(recs, 1))), 2)


class TailTest(unittest.TestCase):
    def test_the_tail_is_never_read_as_an_entry(self):
        data = proj(*song([track(0, 88), track(1, 80, flag=3)], []), *flat(88, 80, 500))
        self.assertEqual(placements(project_records(data), 1), [])
        self.assertEqual(TAIL, len(TAIL_BYTES))


class FlexEntryTest(unittest.TestCase):
    def test_flex_marker_blocks_after_an_entry_are_not_entries(self):
        from logicxkit.logic.services.regions.regions import entry_offsets
        marker_block = bytearray(ENTRY)
        marker_block[6:8] = b"\x01\xaa"                  # a transient marker, as Logic writes it
        events = entry(10, 1) + bytes(marker_block) * 3 + entry(20, 2) + TAIL_BYTES
        self.assertEqual(entry_offsets(events), [0, 4 * ENTRY])
        rows = [track(0, 10), track(1, 20)]
        data = proj(env_obj(10, "a"), env_obj(20, "b"), env_obj(30, "c"),
                    *song(rows, [entry(10, 1), bytes(marker_block), entry(20, 2)]), *flat(10, 20, 30))
        self.assertEqual([(o, r) for _off, o, r in placements(project_records(data), None)], [(10, 1), (20, 2)])
        self.assertEqual(region_errors(data, None), [])


class ExtensionRowTest(unittest.TestCase):
    def test_a_row_marked_at_byte_7_belongs_to_the_entry_before_it(self):
        """A converted 10.8.1 set's first entry runs 96 bytes, its last row marked `0xbe`."""
        from logicxkit.logic.services.regions.regions import entry_blocks
        row = bytearray(16)
        row[7] = 0xBE
        events = entry(10, 1) + bytes(row) + entry(20, 2) + TAIL_BYTES
        self.assertEqual(entry_blocks(events), [(0, 0), (ENTRY + 16, 0)])


class RegionPairTest(unittest.TestCase):
    def test_entry_pairs_come_from_every_sequence_take_folders_included(self):
        from _records import seq_triple
        from logicxkit.logic.services.regions.audio_regions import audio_entry_pairs

        def audio_entry(slot: int, piece: int = 0) -> bytes:
            e = bytearray(ENTRY)
            struct.pack_into("<I", e, 0, 0x24)
            struct.pack_into("<I", e, 44, 4 * slot)
            e[40] = piece
            return bytes(e)

        rows = [track(0, 10), track(1, 20)]
        take_folder = seq_triple(9, slot=48, big=audio_entry(43) + audio_entry(44, 2) + TAIL_BYTES)
        data = proj(env_obj(10, "a"), env_obj(20, "b"), env_obj(30, "c"),
                    *song(rows, [audio_entry(47), audio_entry(63, 1)]), take_folder, *flat(10, 20, 30))
        self.assertEqual(sorted(audio_entry_pairs(project_records(data))), [(172, 0), (176, 2), (188, 0), (252, 1)])


class PieceNumberTest(unittest.TestCase):
    """An entry's piece number is two bytes at +40: a Logic 10.8.1 live set's audio entries are
    numbered well past 255, every one pairing with its record read so, the two bytes after always
    zero (2026-10-25)."""

    def test_a_piece_past_255_is_written_in_two_bytes_and_read_back(self):
        from logicxkit.logic.services.regions.audio_regions import ENTRY_ORDINAL_AT, ENTRY_PIECE_AT, entry_pair
        from logicxkit.logic.services.regions.region_entry import _piece_entry
        base = bytearray(entry(object_id=9, row=1))
        struct.pack_into("<I", base, ENTRY_ORDINAL_AT, 64)                  # an audio entry's file slot word
        base = bytes(base)
        piece = _piece_entry(base, 38400, piece=300)
        self.assertEqual(piece[ENTRY_PIECE_AT:ENTRY_PIECE_AT + 4], (300).to_bytes(2, "little") + b"\0\0")
        self.assertEqual(entry_pair(piece), (64, 300))
        self.assertEqual(entry_pair(_piece_entry(base, 38400, piece=7)), (64, 7))


class PieceStemTest(unittest.TestCase):
    def test_a_piece_drops_its_trailing_number_whatever_it_is_and_a_parent_keeps_its_name(self):
        from logicxkit.logic.services.regions.audio_regions import AudioRegion
        stem = lambda name, piece: AudioRegion("Gtr", 1, name, 38400, 1, None, piece=piece).stem  # noqa: E731
        self.assertEqual(stem("Gtr #02.7", 2), "Gtr #02")          # Logic's counter ran ahead of the piece
        self.assertEqual(stem("take.3", 3), "take")
        self.assertEqual(stem("take", 4), "take")                   # renamed by hand, no suffix
        self.assertEqual(stem("Mix v1.2", 0), "Mix v1.2")           # the parent's own name is left alone
        self.assertEqual(stem(".5", 5), ".5")



class EntryLayoutTest(unittest.TestCase):
    """A marker block after an entry that runs past 80 bytes sits where the entry ends, not at a
    multiple of the entry size; a block cut short at the end is rows of the entry before it."""

    def _block(self) -> bytes:
        from logicxkit.logic.services.regions.regions import MARKER_BYTE, MARKER_BYTES_AT, MARKER_KIND, MARKER_KIND_AT
        b = bytearray(80)
        b[MARKER_KIND_AT] = MARKER_KIND
        for at in MARKER_BYTES_AT:
            b[at] = MARKER_BYTE
        return bytes(b)

    def test_a_block_after_a_long_entry_is_found_where_it_sits(self):
        from logicxkit.logic.services.regions.regions import TAIL, blocks_of, entry_blocks, entry_layout
        row = bytes(7) + b"\xbe" + bytes(8)
        events = entry(10, 1) + row + self._block() + entry(20, 2) + bytes(TAIL)
        self.assertEqual(entry_layout(events), [(0, [96]), (176, [])])
        self.assertEqual(entry_blocks(events), [(0, 1), (176, 0)])
        self.assertEqual(blocks_of(events, 0), [self._block()])

    def test_a_block_cut_short_belongs_to_no_entry_as_a_block(self):
        from logicxkit.logic.services.regions.regions import TAIL, entry_layout
        events = entry(10, 1) + entry(20, 2) + self._block()[:48] + bytes(TAIL)
        self.assertEqual(entry_layout(events), [(0, []), (80, [])])

if __name__ == "__main__":
    unittest.main()
