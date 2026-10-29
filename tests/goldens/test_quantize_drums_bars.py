"""Quantizing a range of bars: only the blocks inside the bars change, a second range adds no
group or pair, meters other than 4/4, and the markers Logic kept on its re-save."""

import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _goldens
from logicxkit.logic.services.regions.audio_regions import read_audio_regions
from logicxkit.logic.services.regions.audio_write import add_audio_region
from logicxkit.logic.services.song.events import BAR_ONE, PPQ
from logicxkit.logic.services.regions.flexmarkers import END, HIT, START, RBA_CODE_AT
from logicxkit.logic.services.arrange.groups import read_groups
from logicxkit.logic.services.stream.stream import HEADER, project_records, reassemble
from logicxkit.logic.services.stream.integrity import regressions, structural_report
from logicxkit.logic.services.regions.quantize_drums import quantize_drums
from logicxkit.logic.services.regions.regions import ENTRY, entry_blocks, region_errors, song_container
from logicxkit.logic.services.song.signature_write import set_time_signature
from logicxkit.logic.services.song.tempo import project_tempo
from logicxkit.logic.services.arrange.tracklist import arrange_run
from logicxkit.logic.services.stream.validate import validate_project
from logicxkit.logicx import project_data
from _quantize import (
    KICK, RATE, SNARE, anchors_only, clicks, entry_slots, hit_targets, marker_blocks, rba_headers, slot_pairs, song_end,
    without_rba_bit,
)


@_goldens.needs("midi-write-resave-logic")
class BarsTest(unittest.TestCase):
    """Three bars of kick; bar 2's hits sit off the quarter grid, the others on the 1/16 grid."""
    BEATS = [0.02, 1.0, 2.05, 3.0, 4.3, 5.02, 6.2, 7.0, 8.3, 9.0, 10.05, 11.0]

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        media = Path(cls.tmp.name) / "Media" / "Audio Files"
        data = project_data(_goldens.path("midi-write-resave-logic"))
        cls.spb = RATE * 60 / project_tempo(data)[1]
        for track in (KICK, SNARE):
            data, _ = add_audio_region(data, track=track, start=BAR_ONE, media_folder=media,
                                       wav=clicks(Path(cls.tmp.name) / f"{track}.wav", cls.BEATS, project_tempo(data)[1]))
        cls.base, cls.wav_of = data, (lambda region: media / region.file.name)
        cls.full, _ = cls.run_on(data, grid=16)
        cls.ranged, cls.report = cls.run_on(cls.full, bars=(2, 2), grid=4)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @classmethod
    def run_on(cls, data, **kw):
        return quantize_drums(data, members=[KICK, SNARE], references=[KICK], wav_of=cls.wav_of, groups_off=("OH",), **kw)

    def split(self, blocks):
        inside = lambda b: b[6] == HIT and 4 * self.spb <= struct.unpack_from("<i", b, 0)[0] < 8 * self.spb  # noqa: E731
        return [b for b in blocks if not inside(b)], [b for b in blocks if inside(b)]

    def test_only_the_blocks_inside_the_bars_change(self):
        was, now = marker_blocks(self.full), marker_blocks(self.ranged)
        now = {oid: blocks for oid, blocks in now.items() if blocks}
        self.assertEqual(len(now), 2)
        for oid, blocks in now.items():
            kept, moved = self.split(blocks)
            self.assertEqual(kept, self.split(was[oid])[0])
            self.assertEqual([struct.unpack_from("<i", b, 0)[0] for b in moved], [struct.unpack_from("<i", b, 0)[0] for b in self.split(was[oid])[1]])
            self.assertEqual([struct.unpack_from("<i", b, 12)[0] / PPQ for b in moved], [4, 5, 6, 7])
        records = [r.raw for i, r in enumerate(project_records(self.ranged)) if i != song_end(self.ranged)]
        self.assertEqual(records, [r.raw for i, r in enumerate(project_records(self.full)) if i != song_end(self.full)])
        self.assertEqual([t[1:] for t in self.report.ranged], [(4, 4, 8, 0)] * 2)
        self.assertIn("bars 2-2", "\n".join(self.report.lines()))

    def test_both_passes_keep_the_project_whole(self):
        for before, after in ((self.base, self.full), (self.full, self.ranged)):
            self.assertEqual((validate_project(after), region_errors(after), regressions(before, after)), ([], [], []))

    def test_a_second_range_adds_no_group_triple_or_registry_pair(self):
        again, report = self.run_on(self.ranged, bars=(3, 3))
        self.assertEqual((report.group_created, [t[1] for t in report.ranged]), (False, [16, 16]))
        self.assertEqual(len([g for g in read_groups(again) if g.name == "Drums"]), 1)
        self.assertEqual((rba_headers(again), slot_pairs(again)), (rba_headers(self.full), slot_pairs(self.full)))
        self.assertEqual((validate_project(again), regressions(self.ranged, again)), ([], []))
        self.assertEqual(self.run_on(self.ranged, bars=(2, 2), grid=4)[0], self.ranged)

    def test_a_region_quantized_for_the_first_time_with_bars(self):
        out, report = self.run_on(self.base, bars=(2, 2), grid=8)
        spt = self.spb / PPQ
        for blocks in (b for b in marker_blocks(out).values() if b):
            self.assertEqual((blocks[0][6], blocks[-1][6], {b[6] for b in blocks[1:-1]}), (START, END, {HIT}))
            kept, moved = self.split(blocks[1:-1])
            self.assertEqual(len(kept), 8)
            for b in kept:
                source, fraction, target = struct.unpack_from("<i", b, 0)[0], struct.unpack_from("<H", b, 10)[0], struct.unpack_from("<i", b, 12)[0]
                self.assertAlmostEqual(target + fraction / 0x10000, source / spt, places=3)
            self.assertEqual([struct.unpack_from("<i", b, 12)[0] / PPQ for b in moved], [4.5, 5, 6, 7])
        self.assertEqual({struct.unpack_from("<h", p, RBA_CODE_AT)[0] for p in rba_headers(out)}, {-8})
        self.assertEqual((len(rba_headers(out)), report.hits), (2, len(self.BEATS)))
        self.assertEqual((validate_project(out), regressions(self.base, out)), ([], []))

    def test_a_member_whose_list_holds_only_anchors_takes_the_references_hits(self):
        """Logic's first quantize writes the hits on the first Q-Reference region alone: the
        other members carry two anchors and play by the group. --bars gives them that list."""
        first = anchors_only(self.full, SNARE)
        out, report = self.run_on(first, bars=(2, 2), grid=4)
        blocks, ids = marker_blocks(out), {r.track: r.object_id for r in read_audio_regions(out)}
        self.assertEqual(blocks[ids[SNARE]], blocks[ids[KICK]])
        self.assertEqual(blocks[ids[KICK]], marker_blocks(self.ranged)[ids[KICK]])
        self.assertEqual((report.borrowed, report.sources), ([(SNARE, KICK, len(self.BEATS))], []))
        self.assertIn(f"{SNARE}: {len(self.BEATS)} hit(s) taken from {KICK}'s list", "\n".join(report.lines()))
        self.assertEqual((validate_project(out), regressions(first, out)), ([], []))

    def test_a_member_without_regions_does_not_stop_the_groups_reuse(self):
        again, report = quantize_drums(self.full, members=[KICK, SNARE, "Audio 3"], references=[KICK], wav_of=self.wav_of,
                                       groups_off=("OH",), bars=(3, 3))
        self.assertEqual((report.group_created, len([g for g in read_groups(again) if g.name == "Drums"])), (False, 1))

    def test_an_entry_naming_its_triple_with_bit_7_clear_counts_as_quantized(self):
        cleared = without_rba_bit(self.full)
        ranged, _ = self.run_on(cleared, bars=(2, 2), grid=4)
        self.assertEqual(marker_blocks(ranged), marker_blocks(self.ranged))
        self.assertEqual((rba_headers(ranged), entry_slots(ranged), slot_pairs(ranged)),
                         (rba_headers(self.full), entry_slots(self.full), slot_pairs(self.full)))
        self.assertEqual((structural_report(ranged)["dangling_files"]["rba"], regressions(cleared, ranged)), ([], []))
        self.assertEqual(self.run_on(cleared, grid=16)[0], self.full)

    def test_the_gate_names_the_triples_a_second_triple_would_orphan(self):
        with mock.patch("logicxkit.logic.services.regions.quantize_drums.rba_sequences", return_value={}):
            doubled, _ = self.run_on(self.full, grid=16)
        self.assertEqual(len(rba_headers(doubled)), 4)
        self.assertIn(f"dangling_files: RBA Sequence triples no entry names 0 -> 2: {sorted(entry_slots(self.full))}",
                      regressions(self.full, doubled))

    def test_refusals(self):
        with self.assertRaisesRegex(ValueError, "never quantized"):
            self.run_on(self.base, bars=(2, 2))
        with self.assertRaisesRegex(ValueError, "hold no hit"):
            self.run_on(self.full, bars=(5, 6))
        with self.assertRaisesRegex(ValueError, "Quantize Off"):
            self.run_on(self.full, bars=(2, 2), grid=0)

    def test_bars_refuse_an_entry_naming_a_sequence_that_is_no_rba_sequence(self):
        renamed = reassemble(self.full, [r.raw[:HEADER + 18] + b"MIDI Region\0" + r.raw[HEADER + 30:]
                                         if r.raw[HEADER + 18:HEADER + 30] == b"RBA Sequence" else r.raw
                                         for r in project_records(self.full)])
        with self.assertRaisesRegex(ValueError, f"{KICK}'s region .* names a sequence that is no RBA Sequence"):
            self.run_on(renamed, bars=(2, 2), grid=4)


@_goldens.needs("midi-write-resave-logic")
class MeterTest(unittest.TestCase):
    """--bars on the song's grid by the meter: a region starting mid-bar, and a 3/4 song."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        media = Path(cls.tmp.name) / "Media" / "Audio Files"
        cls.wav_of = lambda region: media / region.file.name
        plain = project_data(_goldens.path("midi-write-resave-logic"))
        cls.spb = RATE * 60 / project_tempo(plain)[1]

        def quantized(data, start, name):
            for track in (KICK, SNARE):
                data, _ = add_audio_region(data, track=track, start=start, media_folder=media,
                                           wav=clicks(Path(cls.tmp.name) / f"{name}-{track}.wav", BarsTest.BEATS, project_tempo(data)[1]))
            return cls.run_on(data, grid=16)[0]

        cls.midbar = quantized(plain, BAR_ONE + 700, "midbar")
        cls.waltz = quantized(set_time_signature(plain, 3, 4, force=True), BAR_ONE, "waltz")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @classmethod
    def run_on(cls, data, **kw):
        return quantize_drums(data, members=[KICK, SNARE], references=[KICK], wav_of=cls.wav_of, groups_off=("OH",), **kw)

    def test_a_region_starting_mid_bar_is_refused_with_its_offset(self):
        with self.assertRaisesRegex(ValueError, f"{KICK}'s region .* starts 700 ticks into bar 1, off the 1/4 grid"):
            self.run_on(self.midbar, bars=(2, 2), grid=4)

    def test_three_four_bars_move_onto_the_songs_quarters_in_order(self):
        out, report = self.run_on(self.waltz, bars=(4, 4), grid=4)
        was = marker_blocks(self.waltz)
        for oid, blocks in ((oid, b) for oid, b in marker_blocks(out).items() if b):
            targets = hit_targets(blocks)
            self.assertEqual(targets, sorted(set(targets)))
            bar_4 = [struct.unpack_from("<i", b, 12)[0] / PPQ for b in blocks
                     if b[6] == HIT and 9 * self.spb <= struct.unpack_from("<i", b, 0)[0] < 12 * self.spb]
            self.assertEqual(bar_4, [9, 10, 11])
            self.assertEqual([t for t in targets if not 9 * PPQ <= t < 12 * PPQ],
                             [t for t in hit_targets(was[oid]) if not 9 * PPQ <= t < 12 * PPQ])
        self.assertEqual([t[1:] for t in report.ranged], [(4, 3, 9, 0)] * 2)
        self.assertEqual(regressions(self.waltz, out), [])

    def test_a_grid_quantize_drums_does_not_write_is_refused(self):
        with self.assertRaisesRegex(ValueError, "grid 1: quantize-drums writes 4, 8, 16 or 32"):
            self.run_on(self.waltz, bars=(4, 4), grid=1)


@_goldens.needs("songb-bars-9-12-mine", "songb-bars-9-12-logic")
class LogicResavedBarsTest(unittest.TestCase):
    """`--bars` on a take Logic quantized itself, held to Logic's re-save of the copy."""

    @staticmethod
    def marker_lists(key: str) -> list[tuple]:
        import struct
        from logicxkit.logic.services.regions.audio_regions import read_audio_regions
        from logicxkit.logic.services.regions.flexmarkers import block_fields
        from logicxkit.logic.services.stream.stream import HEADER, project_records
        from logicxkit.logic.services.project.project import project_metadata
        path = _goldens.path(key)
        data, count = project_data(path), project_metadata(path).get("tracks")
        records = project_records(data)
        payload = records[song_container(records, arrange_run(records, count)).end].raw[HEADER:]
        names = {r.at: r for r in read_audio_regions(data, count)}
        out = []
        for off, blocks in entry_blocks(payload):
            if off in names and blocks:
                hits = tuple(block_fields(payload[off + ENTRY * (k + 1):off + ENTRY * (k + 2)]) for k in range(blocks))
                out.append((names[off].track, names[off].name, struct.unpack_from("<I", payload, off + 4)[0], hits))
        return out

    def test_logic_kept_every_members_marker_list(self):
        ours, logic = self.marker_lists("songb-bars-9-12-mine"), self.marker_lists("songb-bars-9-12-logic")
        self.assertEqual(ours, logic)
        self.assertEqual([[t, n, len(h)] for t, n, _tick, h in ours], _goldens.fact("songb-bars-9-12-mine", "regions"))
        self.assertEqual(len({len(h) for *_rest, h in ours}), 1)      # every member carries the reference's full list
        for key in ("songb-bars-9-12-mine", "songb-bars-9-12-logic"):
            self.assertEqual(validate_project(project_data(_goldens.path(key))), [])

if __name__ == "__main__":
    unittest.main()
