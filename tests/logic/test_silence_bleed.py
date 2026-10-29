"""The bleed rule: a mic that is never silent while the band plays is cut to where it rises over
its bleed floor and over the bleed its references predict."""

import math
import unittest

import _paths  # noqa: F401
from test_silence import RATE, envelope

from logicxkit.logic.services.regions.audio_regions import AudioRegion
from logicxkit.logic.services.regions.silence import Envelope, bleed_stretches
from logicxkit.logic.services.regions.silence_refs import aligned_references

BLEED, SING = 100, 2000           # -50 dBFS of bleed while the band plays, -24 when the singer sings


class BleedStretchesTest(unittest.TestCase):
    def test_the_singer_is_what_rises_above_the_bleed_floor_while_the_band_plays(self):
        env = envelope([(10, BLEED), (10, SING), (10, BLEED), (10, SING), (10, BLEED)])
        playing = [True] * len(env.peaks)
        stretches, floor_db, usual = bleed_stretches(env, playing, above_db=9, min_gap_s=2, min_keep_s=0.5)
        self.assertEqual(stretches, [(0, 10 * RATE), (20 * RATE, 30 * RATE), (40 * RATE, 50 * RATE)])
        self.assertEqual(usual, [])
        self.assertAlmostEqual(floor_db, 20 * math.log10(BLEED / 32768), places=3)

    def test_the_floor_is_read_where_the_band_plays_not_in_the_gaps_between_songs(self):
        """Half the file is near-silent gaps; the floor is still the bleed level."""
        env = envelope([(40, 1), (10, BLEED), (10, SING), (10, BLEED)])
        playing = [False] * 4000 + [True] * 3000
        stretches, floor_db, _ = bleed_stretches(env, playing, above_db=9, min_gap_s=2, min_keep_s=0.5)
        self.assertEqual(stretches, [(0, 50 * RATE), (60 * RATE, 70 * RATE)])
        self.assertAlmostEqual(floor_db, 20 * math.log10(BLEED / 32768), places=3)

    def test_a_mic_digitally_silent_while_the_band_plays_is_quiet_throughout(self):
        env = envelope([(10, 0)])
        refs = [([BLEED] * len(env.peaks), [True] * len(env.peaks))] * 2
        stretches, floor_db, usual = bleed_stretches(env, [True] * len(env.peaks), above_db=9, min_gap_s=2, min_keep_s=0.5,
                                                     references=refs)
        self.assertEqual((stretches, floor_db, usual), ([(0, 10 * RATE)], -math.inf, [math.inf, math.inf]))

    def test_a_silent_mic_with_nothing_playing_is_left_whole(self):
        env = envelope([(10, 0)])
        self.assertEqual(bleed_stretches(env, [False] * len(env.peaks), above_db=9, min_gap_s=2, min_keep_s=0.5), ([], -math.inf, []))

    def test_a_louder_margin_asks_more_of_the_singer(self):
        env = envelope([(10, BLEED), (10, round(BLEED * 2.5)), (10, BLEED)])
        playing = [True] * len(env.peaks)
        self.assertEqual(bleed_stretches(env, playing, above_db=6, min_gap_s=2, min_keep_s=0.5)[0], [(0, 10 * RATE), (20 * RATE, 30 * RATE)])
        self.assertEqual(bleed_stretches(env, playing, above_db=9, min_gap_s=2, min_keep_s=0.5)[0], [(0, 30 * RATE)])

    def test_drum_hits_in_the_bleed_do_not_count_as_the_singer(self):
        """A 50 ms hit every 400 ms, 26 dB over the floor: the running median over 300 ms never sees
        it, so the stretch runs through; at 10 ms it would be heard every beat."""
        env = envelope([(5, BLEED)] + [(0.05, SING), (0.35, BLEED)] * 25 + [(5, BLEED)])
        playing = [True] * len(env.peaks)
        self.assertEqual(bleed_stretches(env, playing, above_db=9, min_gap_s=2, min_keep_s=0.5)[0], [(0, 20 * RATE)])
        raw = bleed_stretches(env, playing, above_db=9, min_gap_s=2, min_keep_s=0.5, window_ms=0)[0]
        self.assertEqual(raw, [(0, 5 * RATE), (round(14.65 * RATE), 20 * RATE)])     # the last hit ends at 14.65 s

    def test_bleed_that_rises_with_the_band_is_not_the_singer_when_a_reference_level_is_given(self):
        """A loud chorus lifts the bleed 12 dB, over the floor plus 9; the overheads rose the same
        12 dB, so the mic is no further over them than usual: still silence. The singer is."""
        env = envelope([(10, BLEED), (10, 4 * BLEED), (10, BLEED), (10, SING), (10, BLEED)])
        ref = [1000] * 1000 + [4000] * 1000 + [1000] * 3000
        playing = [True] * len(env.peaks)
        self.assertEqual(bleed_stretches(env, playing, above_db=9, min_gap_s=2, min_keep_s=0.5)[0],
                         [(0, 10 * RATE), (20 * RATE, 30 * RATE), (40 * RATE, 50 * RATE)])
        stretches, _floor, usual = bleed_stretches(env, playing, above_db=9, min_gap_s=2, min_keep_s=0.5, references=[(ref, playing)])
        self.assertEqual(stretches, [(0, 30 * RATE), (40 * RATE, 50 * RATE)])
        self.assertAlmostEqual(usual[0], 20 * math.log10(BLEED / 1000), places=3)      # the mic's usual level over the reference

    def test_each_reference_is_scaled_by_the_mics_usual_ratio_to_it(self):
        """A backing mic sits 3 dB under the overheads and 20 dB under the lead's mic. The lead's
        chorus lifts the lead mic 20 dB and the backing mic with it, by its usual 20 dB under: still
        bleed. The band's chorus lifts the overheads and the mic 12 dB together: bleed too. The mic
        rising 20 dB while neither does is the singer, and so is the mic rising to the lead's
        level while the lead sings, 20 dB over the usual."""
        quiet, lead_up, band_up, own, with_lead = 100, 1000, 400, 1000, 10000
        env = envelope([(10, quiet), (10, lead_up), (10, quiet), (10, band_up), (10, quiet), (10, own), (10, quiet), (10, with_lead), (10, quiet)])
        n = len(env.peaks)
        oh = [141] * 3000 + [565] * 1000 + [141] * 5000                        # +3 dB over the mic's quiet; +12 in its chorus
        lead = [1000] * 1000 + [10000] * 1000 + [1000] * 5000 + [10000] * 1000 + [1000] * 1000
        playing = [True] * n
        stretches, _floor, usual = bleed_stretches(env, playing, above_db=9, min_gap_s=2, min_keep_s=0.5,
                                                   references=[(oh, playing), (lead, playing)])
        self.assertEqual(stretches, [(0, 50 * RATE), (60 * RATE, 70 * RATE), (80 * RATE, 90 * RATE)])
        self.assertAlmostEqual(usual[0], -3.0, delta=0.05)
        self.assertAlmostEqual(usual[1], -20.0, delta=0.05)

    def test_a_reference_counts_only_where_it_plays_and_is_left_out_where_it_has_no_level(self):
        """The usual ratio is read while that reference plays: read in the first ten seconds, the
        lead sits 28 dB over the mic and the mic's rise in the next ten clears the bleed; read in
        those ten instead, the rise is the usual ratio and is bleed. Where the lead has no level the
        overheads alone predict the bleed, and where neither has any the floor rule alone decides."""
        env = envelope([(10, 400), (10, 4000), (10, 400), (10, 4000)])
        oh = [565] * 2000 + [0] * 2000
        lead = [10000] * 1000 + [1000] * 1000 + [0] * 2000
        playing = [True] * 4000
        first, second = [True] * 1000 + [False] * 3000, [False] * 1000 + [True] * 1000 + [False] * 2000
        stretches, _floor, usual = bleed_stretches(env, playing, above_db=9, min_gap_s=2, min_keep_s=0.5,
                                                   references=[(oh, playing), (lead, first)])
        self.assertEqual(stretches, [(0, 10 * RATE), (20 * RATE, 30 * RATE)])      # the last rise: the floor alone, heard
        self.assertAlmostEqual(usual[1], 20 * math.log10(400 / 10000), places=3)
        stretches, _floor, usual = bleed_stretches(env, playing, above_db=9, min_gap_s=2, min_keep_s=0.5,
                                                   references=[(oh, playing), (lead, second)])
        self.assertEqual(stretches, [(0, 30 * RATE)])
        self.assertAlmostEqual(usual[1], 20 * math.log10(4000 / 1000), places=3)

    def test_the_gate_may_sit_lower_than_the_margin(self):
        """A singer off the mic rises 5 dB over the floor but 15 dB over the bleed the overheads
        predict (they dropped 10 dB): heard at a 3 dB gate, not at the 9 dB default."""
        env = envelope([(10, 1000), (10, 1778), (10, 1000)])
        oh = [1000] * 1000 + [316] * 1000 + [1000] * 1000
        playing = [True] * 3000
        self.assertEqual(bleed_stretches(env, playing, above_db=9, min_gap_s=2, min_keep_s=0.5, references=[(oh, playing)])[0],
                         [(0, 30 * RATE)])
        self.assertEqual(bleed_stretches(env, playing, above_db=9, min_gap_s=2, min_keep_s=0.5, references=[(oh, playing)], gate_db=3)[0],
                         [(0, 10 * RATE), (20 * RATE, 30 * RATE)])

    def test_a_silent_reference_leaves_the_floor_rule_alone(self):
        """Between songs nothing bleeds; what rises over the floor there is heard as before."""
        env = envelope([(10, BLEED), (10, SING), (10, BLEED)])
        playing = [True] * 1000 + [False] * 2000
        ref = [1000] * 1000 + [0] * 2000
        self.assertEqual(bleed_stretches(env, playing, above_db=9, min_gap_s=2, min_keep_s=0.5, references=[(ref, playing)])[0],
                         [(0, 10 * RATE), (20 * RATE, 30 * RATE)])

    def test_a_short_window_keeps_a_single_hit(self):
        """A 60 ms hit 26 dB over the floor: gone under the 300 ms median, kept at a 30 ms window."""
        env = envelope([(5, BLEED), (0.06, SING), (5, BLEED)])
        playing = [True] * len(env.peaks)
        self.assertEqual(bleed_stretches(env, playing, above_db=9, min_gap_s=0.5, min_keep_s=0.05)[0], [(0, round(10.06 * RATE))])
        self.assertEqual(bleed_stretches(env, playing, above_db=9, min_gap_s=0.5, min_keep_s=0.05, window_ms=30)[0],
                         [(0, 5 * RATE), (round(5.06 * RATE), round(10.06 * RATE))])

    def test_a_tilt_against_a_second_band_of_the_mic_drops_what_is_louder_there(self):
        """Two hits over the floor and over the reference: one with more in the mic's own high band
        than in its band (a snare in a tom mic) is silence once a tilt is asked for."""
        env = envelope([(5, BLEED), (0.5, SING), (5, BLEED), (0.5, SING), (5, BLEED)])
        against = [BLEED] * 500 + [SING // 4] * 50 + [BLEED] * 500 + [SING * 2] * 50 + [BLEED] * 500
        playing = [True] * len(env.peaks)
        self.assertEqual(bleed_stretches(env, playing, above_db=9, min_gap_s=0.5, min_keep_s=0.05, window_ms=30)[0],
                         [(0, 5 * RATE), (round(5.5 * RATE), round(10.5 * RATE)), (11 * RATE, 16 * RATE)])
        self.assertEqual(bleed_stretches(env, playing, above_db=9, min_gap_s=0.5, min_keep_s=0.05, window_ms=30,
                                         against=against, tilt_db=0)[0],
                         [(0, 5 * RATE), (round(5.5 * RATE), 16 * RATE)])

    def test_the_tilt_may_read_the_mic_in_a_third_band(self):
        """The level rule on the wide band; the tilt on the tom's fundamental against the highs."""
        env = envelope([(5, BLEED), (0.5, SING), (5, BLEED), (0.5, SING), (5, BLEED)])
        narrow = [BLEED] * 500 + [SING] * 50 + [BLEED] * 500 + [SING // 8] * 50 + [BLEED] * 500
        against = [BLEED] * 500 + [SING // 2] * 50 + [BLEED] * 500 + [SING // 2] * 50 + [BLEED] * 500
        playing = [True] * len(env.peaks)
        self.assertEqual(bleed_stretches(env, playing, above_db=9, min_gap_s=0.5, min_keep_s=0.05, window_ms=30,
                                         against=against, tilt_db=0, tilted=narrow)[0],
                         [(0, 5 * RATE), (round(5.5 * RATE), 16 * RATE)])

    def test_the_margin_over_the_predicted_bleed_is_above_db_as_a_power_ratio(self):
        """A passage 6 dB over the bleed the reference predicts: heard at 5 dB, silence at 7; the floor
        rule stands aside (gate 0)."""
        env = envelope([(10, BLEED), (10, BLEED * 2), (10, BLEED)])
        playing = [True] * len(env.peaks)
        ref = [1000] * len(env.peaks)
        self.assertEqual(bleed_stretches(env, playing, above_db=5, min_gap_s=2, min_keep_s=0.5, references=[(ref, playing)], gate_db=0)[0],
                         [(0, 10 * RATE), (20 * RATE, 30 * RATE)])
        self.assertEqual(bleed_stretches(env, playing, above_db=7, min_gap_s=2, min_keep_s=0.5, references=[(ref, playing)], gate_db=0)[0],
                         [(0, 30 * RATE)])

    def test_two_references_predict_the_bleed_as_a_power_sum(self):
        """Two references the mic sits at its usual ratio to both predict twice the power, 3 dB over
        the mic: a passage 2.3 dB up is under that sum, though over either alone by 0.8 dB."""
        env = envelope([(10, BLEED), (10, round(BLEED * 1.3)), (10, BLEED)])
        playing = [True] * len(env.peaks)
        ref = [1000] * len(env.peaks)
        self.assertEqual(bleed_stretches(env, playing, above_db=0.5, min_gap_s=2, min_keep_s=0.5, references=[(ref, playing)], gate_db=0)[0],
                         [(0, 10 * RATE), (20 * RATE, 30 * RATE)])
        self.assertEqual(bleed_stretches(env, playing, above_db=0.5, min_gap_s=2, min_keep_s=0.5,
                                         references=[(ref, playing), (ref, playing)], gate_db=0)[0], [(0, 30 * RATE)])

    def test_the_default_window_drops_a_100_ms_hit_and_keeps_a_second_of_phrase(self):
        env = envelope([(5, BLEED), (0.1, SING), (5, BLEED), (1, SING), (5, BLEED)])
        playing = [True] * len(env.peaks)
        by_default = bleed_stretches(env, playing, above_db=9, min_gap_s=0.5, min_keep_s=0.05)[0]
        self.assertEqual(by_default, [(0, round(10.1 * RATE)), (round(11.1 * RATE), round(16.1 * RATE))])
        self.assertEqual(bleed_stretches(env, playing, above_db=9, min_gap_s=0.5, min_keep_s=0.05, window_ms=150)[0],
                         [(0, 5 * RATE), (round(5.1 * RATE), round(10.1 * RATE)), (round(11.1 * RATE), round(16.1 * RATE))])
        self.assertEqual(bleed_stretches(env, playing, above_db=9, min_gap_s=0.5, min_keep_s=0.05, window_ms=3000)[0],
                         [(0, round(16.1 * RATE))])

    def test_a_level_exactly_at_the_gate_is_heard_and_a_tilt_exactly_met_is_kept(self):
        env = envelope([(10, 1000), (10, 2000), (10, 1000)])
        playing = [True] * len(env.peaks)
        exactly_double = 20 * math.log10(2)
        self.assertEqual(bleed_stretches(env, playing, above_db=exactly_double, min_gap_s=2, min_keep_s=0.5)[0],
                         [(0, 10 * RATE), (20 * RATE, 30 * RATE)])
        against = [1000] * 1000 + [2000] * 1000 + [1000] * 1000
        self.assertEqual(bleed_stretches(env, playing, above_db=3, min_gap_s=2, min_keep_s=0.5, against=against, tilt_db=0)[0],
                         [(0, 10 * RATE), (20 * RATE, 30 * RATE)])
        self.assertEqual(bleed_stretches(env, playing, above_db=3, min_gap_s=2, min_keep_s=0.5, against=against, tilt_db=0.01)[0],
                         [(0, 30 * RATE)])

    def test_with_nothing_playing_no_floor_can_be_read_so_nothing_is_cut(self):
        env = envelope([(10, BLEED), (10, SING)])
        self.assertEqual(bleed_stretches(env, [False] * len(env.peaks), above_db=9, min_gap_s=2, min_keep_s=0.5),
                         ([], -math.inf, []))

    def test_the_floor_is_read_over_the_nonzero_levels_so_a_gated_mic_keeps_its_rule(self):
        """A desk-gated direct out is digital zero on most playing hops: the floor is the level it
        does carry, not 0."""
        env = envelope([(10, 0), (10, BLEED), (10, SING), (10, 0), (10, BLEED), (10, 0)])
        playing = [True] * len(env.peaks)
        stretches, floor_db, _ = bleed_stretches(env, playing, above_db=9, min_gap_s=2, min_keep_s=0.5)
        self.assertEqual(stretches, [(0, 20 * RATE), (30 * RATE, 60 * RATE)])
        self.assertAlmostEqual(floor_db, 20 * math.log10(BLEED / 32768), places=3)


class AlignedReferencesTest(unittest.TestCase):
    def test_only_the_hops_inside_the_mic_region_count_as_playing(self):
        """A mic file of 10 s whose region plays 2 to 4 s; the reference plays its whole 10 s file from
        the same song tick: the reference lies beside the mic's file for 10 s, but only the region's
        own 200 hops are marked."""
        hop = RATE // 100
        mic = AudioRegion("Vox", 1, "vox", 38400 + round(2 * RATE / 22.96875), 2 * RATE, None, offset=2 * RATE)
        env = Envelope([500] * 1000, hop, RATE, 10 * RATE)
        ref = AudioRegion("OH", 2, "oh", 38400, 10 * RATE, None, offset=0)
        ref_env = Envelope([1000] * 1000, hop, RATE, 10 * RATE)
        playing, (reference,) = aligned_references(mic, env, [(ref, ref_env)], spt=22.96875, threshold_db=-30, order=("OH",))
        self.assertEqual((sum(playing), playing[199], playing[200], playing[399], playing[400]), (200, False, True, True, False))
        self.assertEqual((sum(reference[1]), max(reference[0]), reference[0][100]), (200, 1000, 0))


if __name__ == "__main__":
    unittest.main()
