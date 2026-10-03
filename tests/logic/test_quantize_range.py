"""Re-quantizing the hits of one marker list inside a bar range (`quantize_range.py`), on
synthetic blocks: 120 BPM at 44.1 kHz, a three-bar region starting at bar 1."""

import argparse
import struct
import unittest
from dataclasses import replace

import _paths  # noqa: F401
from _data import needs
from logicxkit.logic._quantize_cmd import bar_range, register
from logicxkit.logic.services.regions.audio_regions import AudioFile, AudioRegion
from logicxkit.logic.services.song.events import BAR_ONE, PPQ
from logicxkit.logic.services.regions.flexmarkers import (
    END, END_TAIL, GRIDS, HIT, OFF, START, block_fields, grid_of, marker_block, quantize_code, samples_per_tick,
)
from logicxkit.logic.services.regions.quantize_drums import quantize_drums
from logicxkit.logic.services.regions.quantize_range import (
    bar_span, chunks, has_hits, overlaps, region_range, requantize, unmoved,
)
from logicxkit.logic.services.song.signature import Meter, TimeSignature

SPB = 22050
SPT = samples_per_tick(SPB)
FRAMES = 12 * SPB
BAR = 4 * PPQ
BAR_2 = (BAR_ONE + BAR, BAR_ONE + 2 * BAR)
FOUR = Meter([TimeSignature(0, 4, 4)])
WALTZ = Meter([TimeSignature(0, 3, 4)])


def hit(beat: float, target_beat: float, kind: int = HIT) -> bytes:
    return marker_block(round(beat * SPB), round(target_beat * PPQ), kind)


def anchors() -> tuple[bytes, bytes]:
    return marker_block(-SPB, -PPQ, START), marker_block(FRAMES, 12 * PPQ, END)


def fields(blocks):
    return [(b[6], round(block_fields(b)[0] / SPB, 2), round(block_fields(b)[2] / PPQ, 2)) for b in blocks]


class SpanTest(unittest.TestCase):
    def test_bars_are_song_ticks_by_the_meter_last_bar_included(self):
        self.assertEqual(bar_span(Meter([TimeSignature(0, 4, 4)]), 2, 2), BAR_2)
        waltz = Meter([TimeSignature(0, 3, 4)])
        self.assertEqual(bar_span(waltz, 3, 4), (BAR_ONE + 6 * PPQ, BAR_ONE + 12 * PPQ))

    def test_a_backwards_or_pre_roll_range_is_refused(self):
        for first, last in ((3, 2), (0, 2)):
            with self.subTest((first, last)), self.assertRaises(ValueError):
                bar_span(Meter([TimeSignature(0, 4, 4)]), first, last)

    def test_overlap_is_by_the_region_span(self):
        self.assertTrue(overlaps(BAR_ONE, FRAMES, SPT, BAR_2))
        self.assertFalse(overlaps(BAR_ONE, 4 * SPB, SPT, BAR_2))
        self.assertFalse(overlaps(BAR_ONE + 2 * BAR, FRAMES, SPT, BAR_2))

    def test_the_grid_of_each_code(self):
        self.assertEqual([grid_of(quantize_code(d)) for d in GRIDS], [4, 8, 16, 32])
        self.assertEqual((grid_of(0), grid_of(-5), grid_of(2)), (0, None, None))

    def test_only_the_four_measured_grids_have_a_code(self):
        self.assertEqual([grid_of(code) for code in (-14, -12, -2)], [None, None, None])
        for grid in (1, 2, 64):
            with self.subTest(grid), self.assertRaises(ValueError):
                quantize_code(grid)

    def test_the_bars_flag_reads_a_range_or_one_bar(self):
        self.assertEqual((bar_range("17-24"), bar_range("3")), ((17, 24), (3, 3)))
        with self.assertRaises(argparse.ArgumentTypeError):
            bar_range("17-")


@needs("logic", "rba-sequence-12.3.1.json")
class RequantizeTest(unittest.TestCase):
    def plan(self, blocks, grid=4, span=BAR_2, meter=FOUR):
        return requantize(blocks, start=BAR_ONE, frames=FRAMES, spt=SPT, grid=grid, span=span, meter=meter)

    def test_hits_inside_move_to_the_grid_and_every_other_block_keeps_its_bytes(self):
        start, end = anchors()
        before = [hit(2.05, 2.0), hit(3.8, 3.75)]
        inside = [hit(4.3, 4.25), hit(6.2, 6.25)]
        after = [hit(8.3, 8.25)]
        plan = self.plan([start, *before, *inside, *after, end])
        self.assertEqual(plan.blocks[:3], [start, *before])
        self.assertEqual(plan.blocks[-2:], [*after, end])
        self.assertEqual(fields(plan.blocks[3:5]), [(HIT, 4.3, 4.0), (HIT, 6.2, 6.0)])
        self.assertEqual((plan.moved, plan.kept, plan.merged), (2, 3, 0))

    def test_kept_quantize_off_hits_become_transients_with_their_targets(self):
        off = hit(8.3, 8.3, OFF)
        plan = self.plan([hit(4.3, 4.3, OFF), off])
        self.assertEqual([b[6] for b in plan.blocks], [HIT, HIT])
        self.assertEqual(plan.blocks[1][:6] + plan.blocks[1][7:], off[:6] + off[7:])

    def test_hits_sharing_a_target_keep_the_nearest_and_a_kept_target_wins(self):
        kept = hit(3.95, 4.0)                              # bar 1, already on beat 4
        plan = self.plan([kept, hit(4.1, 4.0), hit(5.15, 5.0), hit(4.9, 5.0), hit(6.4, 6.5)])
        self.assertEqual(fields(plan.blocks), [(HIT, 3.95, 4.0), (HIT, 4.9, 5.0), (HIT, 6.4, 6.0)])
        self.assertEqual((plan.moved, plan.kept, plan.merged), (2, 1, 2))

    def test_a_source_outside_the_region_is_placed_by_its_target(self):
        stray = marker_block(-100, round(4.5 * PPQ), HIT)
        plan = self.plan([stray])
        self.assertEqual(plan.moved, 1)
        self.assertEqual(block_fields(plan.blocks[0])[:3], (-100, HIT, 4 * PPQ))

    def test_a_list_with_no_hit_in_the_range_is_unchanged(self):
        blocks = [*anchors()[:1], hit(1.1, 1.0), hit(9.2, 9.0), anchors()[1]]
        plan = self.plan(blocks)
        self.assertEqual((plan.blocks, plan.moved, plan.kept), (blocks, 0, 2))
        self.assertEqual(self.plan(list(anchors())).blocks, list(anchors()))

    def test_a_hit_on_the_range_start_moves_and_one_on_its_end_is_kept(self):
        plan = self.plan([hit(4.0, 3.75), hit(8.0, 8.25)], grid=16)
        self.assertEqual(fields(plan.blocks), [(HIT, 4.0, 4.0), (HIT, 8.0, 8.25)])
        self.assertEqual((plan.moved, plan.kept), (1, 1))

    def test_a_moved_hit_crossing_a_kept_target_is_refused_with_both_bars(self):
        with self.assertRaisesRegex(ValueError, r"bar 2: .*kept hit in bar 1"):
            self.plan([hit(3.9, 4.5), hit(4.1, 4.1)])                   # 4.1 -> 4.0, before the kept 4.5
        with self.assertRaisesRegex(ValueError, r"bar 2: .*kept hit in bar 3"):
            self.plan([hit(7.6, 7.6), hit(8.3, 7.9)])                   # 7.6 -> 8.0, past the kept 7.9

    def test_a_block_between_hits_that_is_no_hit_is_refused(self):
        with self.assertRaisesRegex(ValueError, "kind 03"):
            self.plan([hit(1.0, 1.0), anchors()[1], hit(4.3, 4.25)])

    def test_unmoved_blocks_target_their_own_place(self):
        (b,) = unmoved([100000], SPT)
        source, kind, whole, fraction = block_fields(b)
        self.assertEqual((source, kind, whole), (100000, HIT, 4353))
        self.assertAlmostEqual(whole + fraction / 0x10000, 100000 / SPT, places=4)
        self.assertEqual(chunks(b + b + b"\0"), [b, b])
        self.assertTrue(has_hits([b]))
        self.assertFalse(has_hits(list(anchors())))
        self.assertEqual(struct.unpack_from("<i", b, 12)[0], whole)


@needs("logic", "rba-sequence-12.3.1.json")
class RegionRangeTest(unittest.TestCase):
    REGION = AudioRegion("Kick", 1, "Kick#01", BAR_ONE, FRAMES, AudioFile("k.wav", "", 0, "WAVE", 0, FRAMES, 44100, 1, 24))
    HITS = [round(b * SPB) for b in (1.02, 4.3, 9.1)]

    def run_on(self, blocks, had_code, grid=None, span=BAR_2, region=None, meter=FOUR, borrowed=None):
        calls = []
        detect = lambda: calls.append(1) or (self.HITS, 44100)  # noqa: E731
        return region_range(region or self.REGION, blocks, had_code=had_code, detect=detect, bpm=120, grid=grid,
                            span=span, meter=meter, borrowed=borrowed), calls

    def test_a_region_with_anchors_only_takes_the_borrowed_hits_and_reads_no_audio(self):
        start, end = anchors()
        lent = [hit(1.02, 1.02), hit(4.3, 4.3, OFF), hit(9.1, 9.1)]
        (plan, _grid, _spt), calls = self.run_on([start, end], had_code=-6, borrowed=lent)
        self.assertEqual((calls, plan.blocks[0], plan.blocks[-1], plan.kept, plan.moved), ([], start, end, 2, 1))
        self.assertEqual(fields(plan.blocks[1:-1]), [(HIT, 1.02, 1.02), (HIT, 4.3, 4.25), (HIT, 9.1, 9.1)])

    def test_a_quantized_region_without_hit_blocks_keeps_its_anchors_and_gets_the_hits(self):
        start, end = anchors()
        (plan, grid, _spt), calls = self.run_on([start, end], had_code=-6)
        self.assertEqual((grid, calls[:1], plan.blocks[0], plan.blocks[-1]), (16, [1], start, end))
        self.assertEqual(fields(plan.blocks[1:-1]), [(HIT, 1.02, 1.02), (HIT, 4.3, 4.25), (HIT, 9.1, 9.1)])

    def test_a_first_quantize_writes_fresh_anchors_around_the_listed_hits(self):
        flexed = marker_block(FRAMES + END_TAIL, 12 * PPQ, END)
        (plan, grid, _spt), calls = self.run_on([anchors()[0], hit(4.3, 4.3, OFF), flexed], had_code=None, grid=8)
        self.assertEqual((grid, calls, plan.blocks[-1]), (8, [], anchors()[1]))
        self.assertEqual(fields(plan.blocks[1:-1]), [(HIT, 4.3, 4.5)])

    def test_a_quantized_region_with_no_blocks_gets_fresh_anchors(self):
        (plan, _grid, _spt), _calls = self.run_on([], had_code=-6)
        self.assertEqual((plan.blocks[0], plan.blocks[-1]), anchors())
        self.assertEqual(fields(plan.blocks[1:-1]), [(HIT, 1.02, 1.02), (HIT, 4.3, 4.25), (HIT, 9.1, 9.1)])

    def test_a_region_whose_own_grid_is_not_the_songs_is_refused(self):
        cases = {"mid-bar": (replace(self.REGION, start=BAR_ONE + 700), FOUR, 32, "starts 700 ticks into bar 1"),
                 "an eighth in, on quarters": (replace(self.REGION, start=BAR_ONE + 480), FOUR, 4, "starts 480 ticks into bar 1"),
                 "7/8 on quarters": (self.REGION, Meter([TimeSignature(0, 7, 8)]), 4, r"bar 1 \(3360 ticks\) is not whole 1/4 notes")}
        for name, (region, meter, grid, why) in cases.items():
            with self.subTest(name), self.assertRaisesRegex(ValueError, f"Kick's region 'Kick#01' {why}.*--bars"):
                self.run_on([hit(4.3, 4.25)], had_code=-6, grid=grid, region=region, meter=meter)

    def test_a_region_a_beat_into_the_song_takes_the_songs_quarter_grid(self):
        region = replace(self.REGION, start=BAR_ONE + PPQ)
        (plan, _g, _s), _c = self.run_on([hit(2.8, 2.75), hit(3.3, 3.25), hit(7.2, 7.25)], had_code=-6, grid=4, region=region)
        self.assertEqual(fields(plan.blocks), [(HIT, 2.8, 2.75), (HIT, 3.3, 3.0), (HIT, 7.2, 7.25)])

    def test_three_four_bars_snap_to_the_songs_quarters(self):
        bar_4 = bar_span(WALTZ, 4, 4)
        blocks = [hit(8.8, 8.75), hit(9.2, 9.25), hit(10.6, 10.5), hit(12.1, 12.0)]
        (plan, _g, _s), _c = self.run_on(blocks, had_code=-6, grid=4, span=bar_4, meter=WALTZ)
        self.assertEqual(fields(plan.blocks), [(HIT, 8.8, 8.75), (HIT, 9.2, 9.0), (HIT, 10.6, 11.0), (HIT, 12.1, 12.0)])

    def test_outside_the_range_or_without_a_grid(self):
        self.assertEqual(self.run_on([hit(1.0, 1.0)], had_code=-6, span=(BAR_ONE + 3 * BAR, BAR_ONE + 4 * BAR)), (None, []))
        for code in (None, 0):
            with self.subTest(code), self.assertRaisesRegex(ValueError, "--grid"):
                self.run_on([hit(4.3, 4.3)], had_code=code)


class GridTest(unittest.TestCase):
    MEASURED = "4, 8, 16 or 32"

    def test_the_grid_help_lists_what_quantize_drums_writes(self):
        parser = argparse.ArgumentParser()
        register(parser.add_subparsers())
        sub = parser._subparsers._group_actions[0].choices["quantize-drums"]
        (grid,) = [a for a in sub._actions if a.dest == "grid"]
        self.assertEqual(", ".join(map(str, GRIDS[:-1])) + f" or {GRIDS[-1]}", self.MEASURED)
        self.assertIn(self.MEASURED, grid.help)

    def test_a_grid_it_does_not_write_is_refused_with_the_ones_it_does(self):
        for grid in (0, 1, 2, 3, 12, 64):
            with self.subTest(grid), self.assertRaisesRegex(ValueError, f"^grid {grid}: quantize-drums writes {self.MEASURED}"):
                quantize_drums(b"", members=["Kick"], references=["Kick"], wav_of=lambda region: None, grid=grid)


if __name__ == "__main__":
    unittest.main()
