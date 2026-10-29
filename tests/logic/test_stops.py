"""The stop finder on synthetic quiet runs: gaps, blips absorbed, gaps merged into a stop, a short
stop ignored, a short stretch of playing left out."""

import unittest

import _paths  # noqa: F401
from logicxkit.logic.services.regions.stops import band_quiet, find_stops, gaps, merged_stops

HOP = 0.01


def runs(*parts: tuple[bool, float]) -> list[bool]:
    """Quiet flags from (quiet, seconds) parts."""
    out: list[bool] = []
    for quiet, seconds in parts:
        out += [quiet] * round(seconds / HOP)
    return out


class StopsTest(unittest.TestCase):
    def test_band_quiet_needs_every_track_quiet_and_a_short_track_is_quiet_past_its_end(self):
        bass, kick = [False, True, True, True], [False, False, True]
        self.assertEqual(band_quiet([bass, kick], 5), [False, False, True, True, True])

    def test_gaps_keep_runs_long_enough_and_absorb_a_blip(self):
        q = runs((False, 2), (True, 0.4), (False, 2), (True, 1.0), (False, 0.2), (True, 1.0), (False, 2))
        self.assertEqual(gaps(q, hop_s=HOP, min_gap_s=0.5, min_keep_s=0.3), [(440, 660)])

    def test_gaps_merge_into_a_stop_and_a_short_stop_is_ignored(self):
        found = [(100, 200), (500, 700), (5000, 5050), (9000, 10200)]
        self.assertEqual(merged_stops(found, hop_s=HOP, merge_s=15, min_stop_s=10), [(9000, 10200)])
        self.assertEqual(merged_stops(found, hop_s=HOP, merge_s=15, min_stop_s=5), [(100, 700), (9000, 10200)])

    def test_find_stops_lays_out_songs_and_leaves_a_short_bit_out(self):
        q = runs((False, 120), (True, 12), (False, 20), (True, 12), (False, 90), (True, 11))
        s = find_stops(q, hop_s=HOP, min_gap_s=0.5, min_keep_s=0.3, merge_s=15, min_stop_s=10, min_song_s=45)
        self.assertEqual(s.stops, [(12000, 13200), (15200, 16400), (25400, 26500)])
        self.assertEqual(s.songs, [(0, 12000), (16400, 25400)])
        self.assertEqual(s.short, [(13200, 15200)])
        self.assertEqual(s.hops, 26500)

    def test_a_sound_of_exactly_min_keep_splits_the_gap_and_a_song_of_exactly_min_song_counts(self):
        q = runs((False, 2), (True, 1.0), (False, 0.3), (True, 1.0), (False, 2))
        self.assertEqual(gaps(q, hop_s=HOP, min_gap_s=0.5, min_keep_s=0.3), [(200, 300), (330, 430)])
        q = runs((False, 45), (True, 12), (False, 60))
        s = find_stops(q, hop_s=HOP, min_gap_s=0.5, min_keep_s=0.3, merge_s=15, min_stop_s=10, min_song_s=45)
        self.assertEqual((s.songs, s.short), ([(0, 4500), (5700, 11700)], []))

    def test_the_first_song_starts_where_the_sound_does_and_the_last_ends_where_it_stops(self):
        q = runs((True, 3), (False, 60), (True, 12), (False, 60), (True, 2))
        s = find_stops(q, hop_s=HOP, min_gap_s=0.5, min_keep_s=0.3, merge_s=15, min_stop_s=10, min_song_s=45)
        self.assertEqual((s.songs, s.short, s.stops), ([(300, 6300), (7500, 13500)], [], [(6300, 7500)]))

    def test_a_song_reaching_the_end_counts(self):
        q = runs((False, 60), (True, 12), (False, 60))
        s = find_stops(q, hop_s=HOP, min_gap_s=0.5, min_keep_s=0.3, merge_s=15, min_stop_s=10, min_song_s=45)
        self.assertEqual(s.songs, [(0, 6000), (7200, 13200)])


if __name__ == "__main__":
    unittest.main()
