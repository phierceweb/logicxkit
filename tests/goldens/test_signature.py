"""The signature track: time signatures, key numbers and bar arithmetic across a change.

The real-file part of tests/logic/test_signature.py; skips without the owner's files."""

import unittest
import _goldens
import _paths
from logicxkit.logic.services.signature import meter, read_signatures
from logicxkit.logicx import project_data

SONGS = sorted(p for d in ("mixes", "legacy") for p in (_paths.RESOURCES / d).glob("*/*.logicx"))
FIVE = _goldens.path("meter-song")


@unittest.skipUnless(SONGS, "no resources copies")
class GoldenTest(unittest.TestCase):
    def test_every_band_song_is_four_four_in_key_seven(self):
        for song in SONGS:
            times, keys = read_signatures(project_data(song))
            self.assertEqual([(t.tick, t.numerator, t.denominator) for t in times], [(0, 4, 4)], song)
            self.assertEqual([k.number for k in keys], [7], song)

    @unittest.skipUnless(FIVE, "no meter-change golden")
    def test_meter_change_reads_as_the_song_has_it(self):
        data = project_data(FIVE)
        times, _keys = read_signatures(data)
        self.assertEqual([[t.numerator, t.denominator] for t in times], _goldens.fact("meter-song", "meters"))
        self.assertEqual(meter(data).bar(times[1].tick), float(_goldens.fact("meter-song", "change_bar")))


if __name__ == "__main__":
    unittest.main()
