"""The write gate's region checks on synthetic projects: a song container with a MIDI region
whose sequence is registered, an audio region ranking onto its region and file records, and a
flexed entry with its marker blocks."""

import struct
import unittest

from _records import _slotted, chan, env_obj, gnos, proj, rec, seq_triple, track, uuid
from test_regions import flat, song

from logicxkit.logic.services.integrity import regressions, require_no_regression, structural_report
from logicxkit.logic.services.integrity_regions import NO_SLOT, region_keys
from logicxkit.logic.services.stream import HEADER, project_records
from logicxkit.logic.services.regions import ENTRY, MARKER_BYTE, MARKER_BYTES_AT, MARKER_KIND, MARKER_KIND_AT
from logicxkit.logic.services.reorder import move_track

MIDI, AUDIO = 0x20, 0x24
BAR = 3840
COUNT = 3
KICK, BASS, KEYS = 88, 144, 120


def entry(kind: int, object_id: int, row: int, *, tick: int, slot: int = NO_SLOT, counter: int = 0,
          flexed: bool = False) -> bytes:
    e = bytearray(ENTRY)
    struct.pack_into("<H", e, 0, kind)
    struct.pack_into("<I", e, 4, 34560 + tick)
    struct.pack_into("<H", e, 16, object_id)
    struct.pack_into("<H", e, 20, row)
    struct.pack_into("<I", e, 32, slot)
    struct.pack_into("<I", e, 44, 4 * counter)
    e[15] = 0x10 if flexed else 0
    return bytes(e)


def block(source: int, target: int | None = None) -> bytes:
    b = bytearray(ENTRY)
    struct.pack_into("<i", b, 0, source)
    struct.pack_into("<i", b, 12, source // 20 if target is None else target)
    b[6], b[MARKER_KIND_AT] = 0x01, MARKER_KIND
    for at in MARKER_BYTES_AT:
        b[at] = MARKER_BYTE
    return bytes(b)


def audio_file(name: str, slot: int) -> bytes:
    encoded = name.encode("utf-16-le")
    return _slotted(rec(b"lFuA", 0xFFFF, 0xFFFF, (bytes(8) + struct.pack("<H", len(encoded) // 2) + encoded).ljust(64, b"\0")), slot)


def audio_region(n: int, piece: int = 0) -> bytes:
    return _slotted(rec(b"gRuA", piece, 0xFFFF, bytes([n]) * 96), 4 * n)


FILES = ("bass-1.wav", "bass-2.wav")


def rba_named(triple: bytes) -> bytes:
    return triple[:HEADER + 18] + b"RBA Sequence" + triple[HEADER + 30:]


def project(entries: list[bytes], *, files: tuple = FILES, regions=2,
            registered: tuple[int, ...] | None = (100,), triples: tuple[int, ...] = (100,),
            rba: tuple[int, ...] = (), extra: tuple[bytes, ...] = ()) -> bytes:
    """Kick with a MIDI region (slot 100), Bass with two audio regions (slots 0 and 4, playing
    ``files`` by position — None keeps a slot empty), Keys empty; the arrange rows in their song
    container, then the flat list. ``regions``: a count, or the record slots' indexes with
    ``(index, piece)`` for a split's piece. ``registered=None`` leaves the gnoS record out;
    ``rba`` names those slots' triples RBA Sequence; ``extra`` records go in after the objects."""
    rows = [track(0, KICK), track(1, BASS), track(2, KEYS), track(3, 80, flag=3)]
    registry = () if registered is None else (gnos(KICK, BASS, KEYS, 80, slots=registered),)
    which = range(regions) if isinstance(regions, int) else regions
    return proj(*registry,
                env_obj(KICK, "Kick"), env_obj(BASS, "Bass"), env_obj(KEYS, "Keys"), env_obj(80, "Master", grouping=True),
                *extra,
                *(audio_file(name, 4 * k) for k, name in enumerate(files) if name),
                *(audio_region(*k) if isinstance(k, tuple) else audio_region(k) for k in which),
                *song(rows, entries),
                *((rba_named if slot in rba else bytes)(seq_triple(20 + k, slot=slot)) for k, slot in enumerate(triples)),
                *flat(KICK, BASS, KEYS, 80, 500))


def standard() -> list[bytes]:
    return [entry(MIDI, KICK, 1, tick=BAR, slot=100),
            entry(AUDIO, BASS, 2, tick=BAR, counter=0),
            entry(AUDIO, BASS, 2, tick=2 * BAR, counter=1, flexed=True), block(-13230), block(0), block(44100)]


class CleanTest(unittest.TestCase):
    def test_the_fixture_reads_and_has_no_region_problems(self):
        report = structural_report(project(standard()))
        self.assertIsNone(report["unreadable"])
        self.assertEqual([(p.key[0], p.blocks, p.slot, p.counter, p.file) for p in report["regions"]],
                         [(KICK, 0, 100, None, None), (BASS, 0, None, 0, "bass-1.wav"), (BASS, 3, None, 4, "bass-2.wav")])
        self.assertEqual(report["dangling_files"], {"entries": [], "records": [], "unfiled": [], "files": [], "doubled": [], "rba": []})
        self.assertEqual((report["unregistered_slots"], report["marker_blocks"]), ([], []))

    def test_a_row_move_renumbers_rows_and_keeps_every_region(self):
        data = project(standard())
        moved = move_track(data, KEYS, before=KICK, track_count=COUNT)
        self.assertNotEqual(moved, data)
        self.assertEqual(regressions(data, moved), [])


class LostRegionsTest(unittest.TestCase):
    def test_a_dropped_entry_is_refused_and_named(self):
        entries = standard()
        with self.assertRaisesRegex(ValueError, r"lost_regions: 1 .*object 144 at tick 42240 \(type 0x24\)"):
            require_no_regression(project(entries), project(entries[:1] + entries[2:], regions=2))

    def test_a_declared_deletion_passes(self):
        data = project(standard())
        entries = standard()
        dropped = region_keys(project_records(data))[1]
        after = project(entries[:1] + entries[2:], files=(None, FILES[1]), regions=(1,))
        self.assertEqual(regressions(data, after, removed=[dropped]), [])

    def test_a_deleted_entry_that_leaves_its_region_record_is_named(self):
        data = project(standard())
        dropped = region_keys(project_records(data))[1]
        found = regressions(data, project(standard()[:1] + standard()[2:]), removed=[dropped])
        self.assertEqual(found, ["dangling_files: region records no entry names 0 -> 1: [(0, 0)]"])

    def test_a_dropped_entry_sharing_its_slot_is_named_once(self):
        before = [entry(MIDI, KICK, 1, tick=BAR, slot=100), entry(MIDI, KEYS, 3, tick=BAR, slot=100)]
        self.assertEqual(regressions(project(before), project(before[:1])),
                         ["lost_regions: 1 region(s) the input placed are gone from the song container: "
                          "['object 120 at tick 42240 (type 0x20)']"])

    def test_a_region_moved_to_another_track_is_lost_from_the_first(self):
        entries = standard()
        entries[0] = entry(MIDI, KEYS, 3, tick=BAR, slot=100)
        found = regressions(project(standard()), project(entries))
        self.assertTrue(any(f.startswith("lost_regions:") and "object 88" in f for f in found), found)


class DanglingFilesTest(unittest.TestCase):
    def test_an_extra_region_record_is_refused_and_named(self):
        with self.assertRaisesRegex(ValueError, r"dangling_files: region records no entry names 0 -> 1: \[\(8, 0\)\]"):
            require_no_regression(project(standard()), project(standard(), regions=3))

    def test_an_entry_with_no_region_record_is_refused(self):
        found = regressions(project(standard()), project(standard() + [entry(AUDIO, KEYS, 3, tick=BAR, counter=7)]))
        self.assertEqual([f for f in found if f.startswith("dangling_files")],
                         ["dangling_files: audio entries with no region record 0 -> 1: [(28, 0)]"])

    def test_a_lost_file_record_is_refused(self):
        found = regressions(project(standard()), project(standard(), files=FILES[:1]))
        self.assertIn("dangling_files: region records with no file record 0 -> 1: [(4, 0)]", found)
        self.assertTrue(any(f.startswith("dangling_files: 1 audio placement(s) now play another file") for f in found), found)

    def test_extra_region_records_the_input_had_stay_silent(self):
        data = project(standard(), files=FILES[:1], regions=3)
        report = structural_report(data)["dangling_files"]
        self.assertEqual((report["records"], report["unfiled"]), ([(8, 0)], [(4, 0), (8, 0)]))
        self.assertEqual(regressions(data, move_track(data, KEYS, before=KICK, track_count=COUNT)), [])

    def test_a_stray_file_record_is_refused_and_the_regions_it_repaired_named(self):
        found = regressions(project(standard()), project(standard(), files=("bass-2.wav",) + FILES))
        self.assertIn("dangling_files: file records no region record names 0 -> 1: [8]", found)
        self.assertIn("dangling_files: 2 audio placement(s) now play another file: "
                      "['object 144 at tick 42240 (type 0x24): bass-1.wav -> bass-2.wav', "
                      "'object 144 at tick 46080 (type 0x24): bass-2.wav -> bass-1.wav']", found)

    def test_a_split_piece_with_its_own_record_passes(self):
        entries = standard() + [entry(AUDIO, BASS, 2, tick=3 * BAR, counter=1)]
        piece = bytearray(entries[-1])
        piece[40] = 1
        entries[-1] = bytes(piece)
        found = regressions(project(standard()), project(entries, regions=(0, 1, (1, 1))))
        self.assertEqual([f for f in found if not f.startswith("sequence link errors")], [])   # the fixture's index table is its song container

    def test_audio_entries_trading_counters_are_refused(self):
        entries = standard()
        entries[1], entries[2] = (entry(AUDIO, BASS, 2, tick=BAR, counter=1),
                                  entry(AUDIO, BASS, 2, tick=2 * BAR, counter=0, flexed=True))
        found = regressions(project(standard()), project(entries))
        self.assertTrue(any(f.startswith("dangling_files: 2 audio placement(s) now play another file") for f in found), found)

    def test_extra_file_records_the_input_had_stay_silent(self):
        data = project(standard(), files=FILES + ("spare.wav",))
        self.assertEqual(structural_report(data)["dangling_files"]["files"], [8])
        self.assertEqual(regressions(data, move_track(data, KEYS, before=KICK, track_count=COUNT)), [])


class OrphanedRbaTest(unittest.TestCase):
    KW = {"registered": (100, 104), "triples": (100, 104), "rba": (104,)}

    def test_an_rba_sequence_no_entry_names_any_more_is_refused(self):
        before = project([*standard()[:2], entry(AUDIO, BASS, 2, tick=2 * BAR, counter=1, flexed=True, slot=104),
                          *standard()[3:]], **self.KW)
        self.assertEqual(structural_report(before)["dangling_files"]["rba"], [])
        with self.assertRaisesRegex(ValueError, r"dangling_files: RBA Sequence triples no entry names 0 -> 1: \[104\]"):
            require_no_regression(before, project(standard(), **self.KW))

    def test_one_the_input_had_stays_silent(self):
        data = project(standard(), **self.KW)
        self.assertEqual(structural_report(data)["dangling_files"]["rba"], [104])
        self.assertEqual(regressions(data, move_track(data, KEYS, before=KICK, track_count=COUNT)), [])


class MovedRegionsTest(unittest.TestCase):
    def test_two_midi_regions_trading_tracks_at_one_tick_are_refused_by_slot(self):
        before = [entry(MIDI, KICK, 1, tick=BAR, slot=100), entry(MIDI, KEYS, 3, tick=BAR, slot=104)]
        after = [entry(MIDI, KICK, 1, tick=BAR, slot=104), entry(MIDI, KEYS, 3, tick=BAR, slot=100)]
        kw = {"registered": (100, 104), "triples": (100, 104)}
        found = regressions(project(before, **kw), project(after, **kw))
        self.assertEqual(found, ["moved_regions: 2 region(s) whose sequence slot or audio counter now sits "
                                 "elsewhere: ['slot 100: object 88 at tick 42240 (type 0x20) -> object 120 at "
                                 "tick 42240 (type 0x20)', 'slot 104: object 120 at tick 42240 (type 0x20) -> "
                                 "object 88 at tick 42240 (type 0x20)']"])

    def test_two_audio_regions_trading_tracks_at_one_tick_are_refused_by_counter(self):
        before = [entry(AUDIO, BASS, 2, tick=BAR, counter=0), entry(AUDIO, KEYS, 3, tick=BAR, counter=1)]
        after = [entry(AUDIO, KEYS, 3, tick=BAR, counter=0), entry(AUDIO, BASS, 2, tick=BAR, counter=1)]
        found = regressions(project(before), project(after))
        self.assertTrue(any(f.startswith("moved_regions: 2 ") and "counter 0: object 144" in f for f in found), found)

    def test_a_declared_deletion_of_a_shared_slot_passes(self):
        before = [entry(MIDI, KICK, 1, tick=BAR, slot=100), entry(MIDI, KEYS, 3, tick=BAR, slot=100)]
        data = project(before)
        gone = region_keys(project_records(data))[1]
        self.assertEqual(regressions(data, project(before[:1]), removed=[gone]), [])


class UnregisteredSlotsTest(unittest.TestCase):
    def test_a_region_slot_without_its_registry_pair_is_refused_and_named(self):
        before = project(standard(), triples=(100, 104))
        after = project(standard() + [entry(MIDI, KEYS, 3, tick=BAR, slot=104)], triples=(100, 104))
        with self.assertRaisesRegex(ValueError, r"unregistered_slots: 1 .*object 120 at tick 42240 \(type 0x20\): "
                                                r"slot 104 has no registry entry"):
            require_no_regression(before, after)

    def test_a_slot_naming_no_sequence_is_refused(self):
        found = regressions(project(standard()), project(standard() + [entry(MIDI, KEYS, 3, tick=BAR, slot=108)],
                                                         registered=(100, 108)))
        self.assertIn("slot 108 names no sequence", "".join(found))

    def test_a_lost_registry_record_leaves_every_slotted_entry_unregistered(self):
        found = regressions(project(standard()), project(standard(), registered=None))
        self.assertIn("unregistered_slots: 1 region entr(ies) whose slot has no sequence or no registry pair: "
                      "['object 88 at tick 42240 (type 0x20): slot 100 has no registry entry']", found)

    def test_an_unregistered_slot_the_input_had_stays_silent(self):
        data = project(standard(), registered=())
        self.assertEqual(len(structural_report(data)["unregistered_slots"]), 1)
        self.assertEqual(regressions(data, move_track(data, KEYS, before=KICK, track_count=COUNT)), [])


class MarkerBlocksTest(unittest.TestCase):
    def test_a_block_that_lost_its_mark_is_refused_and_named(self):
        entries = standard()
        broken = bytearray(entries[4])
        broken[MARKER_KIND_AT] = 0
        entries[4] = bytes(broken)
        with self.assertRaisesRegex(ValueError, r"marker_blocks: 1 .*object 144 at tick 46080 \(type 0x24\), "
                                                r"marker block 2: 0x88 bytes without the 0xAA mark"):
            require_no_regression(project(standard()), project(entries))

    def test_a_block_cut_short_is_refused(self):
        entries = standard()
        entries[-1] = entries[-1][:40]
        found = regressions(project(standard()), project(entries))
        self.assertIn("marker_blocks: 1", "".join(found))
        self.assertIn("not whole 80-byte chunks", "".join(found))

    def test_blocks_before_the_first_entry_are_refused(self):
        found = regressions(project(standard()), project([block(0)] + standard()))
        self.assertIn("marker block 1 before the first entry", "".join(found))

    def test_a_flexed_entry_losing_its_blocks_is_refused_and_named(self):
        found = regressions(project(standard()), project(standard()[:3]))
        self.assertIn("marker_blocks: 1 flexed entr(ies) lost their marker blocks: "
                      "['object 144 at tick 46080 (type 0x24): 3 -> 0']", found)

    def test_a_midi_entry_gaining_blocks_is_refused(self):
        entries = standard()
        found = regressions(project(entries), project([entries[0], block(0)] + entries[1:]))
        self.assertEqual(found, ["marker_blocks: 1 MIDI entr(ies) gained marker blocks: "
                                 "['object 88 at tick 42240 (type 0x20): 0 -> 1']"])

    def test_an_entry_slipped_between_a_flexed_entry_and_its_blocks_is_refused_twice(self):
        e = standard()
        found = regressions(project(e), project([e[1], e[2], e[0]] + e[3:]))
        self.assertEqual(found, ["marker_blocks: 1 flexed entr(ies) lost their marker blocks: "
                                 "['object 144 at tick 46080 (type 0x24): 3 -> 0']",
                                 "marker_blocks: 1 MIDI entr(ies) gained marker blocks: "
                                 "['object 88 at tick 42240 (type 0x20): 0 -> 3']"])

    def test_audio_block_counts_changing_or_growing_from_zero_pass(self):
        e = standard()
        requantized = [e[0], e[1], block(-4410), block(0), e[2], block(-13230), block(44100)]
        self.assertEqual(regressions(project(e), project(requantized)), [])

    def test_hit_targets_that_stop_rising_are_refused_and_named(self):
        for name, target in (("backwards", -1), ("repeated", 0)):
            entries = standard()
            entries[5] = block(44100, target)
            with self.subTest(name), self.assertRaisesRegex(
                    ValueError, r"marker_blocks: 1 .*object 144 at tick 46080 \(type 0x24\), marker block 3: "
                                r"target at or before the previous hit's"):
                require_no_regression(project(standard()), project(entries))

    def test_a_broken_block_the_input_had_stays_silent(self):
        entries = standard()
        entries[5] = entries[5][:MARKER_KIND_AT] + b"\0" + entries[5][MARKER_KIND_AT + 1:]
        data = project(entries)
        self.assertEqual(len(structural_report(data)["marker_blocks"]), 1)
        self.assertEqual(regressions(data, move_track(data, KEYS, before=KICK, track_count=COUNT)), [])


class NamelessObjectIndexTest(unittest.TestCase):
    def test_the_index_of_an_object_whose_name_does_not_decode_is_checked(self):
        nameless = (env_obj(500, b"Gitarre \xfc"), chan(272, "Audio 1", uuid=uuid(500)))
        data = project(standard(), extra=nameless)
        report = structural_report(data)
        self.assertIsNone(report["unreadable"])
        self.assertEqual(report["bad_object_index"], [500])


if __name__ == "__main__":
    unittest.main()
