"""The signature track: time signatures, key numbers and bar arithmetic across a change.

The real-file part of tests/logic/test_signature.py; skips without the owner's files."""

import unittest
import _goldens
from logicxkit.logic.services.song.signature import meter, read_signatures
from logicxkit.logicx import project_data

SONGS = _goldens.sessions()
FIVE = _goldens.path("meter-song")
LIST_KEYS = ["signature-list-base-logic", "signature-meter-created-logic", "signature-meter-5-8-bar-6-logic",
             "signature-meter-3-8-bar-6-logic", "signature-key-created-logic", "signature-key-a-minor-logic"]


@unittest.skipUnless(SONGS, "no owner's session on this machine")
class GoldenTest(unittest.TestCase):
    def test_every_session_reads_the_signatures_its_manifest_records(self):
        for key in _goldens.session_keys():
            song = _goldens.path(key)
            if song is None:
                continue
            with self.subTest(key):
                times, keys = read_signatures(project_data(song))
                self.assertEqual([[t.tick, t.numerator, t.denominator] for t in times], _goldens.fact(key, "signatures"))
                self.assertEqual([k.number for k in keys], _goldens.fact(key, "key_numbers"))

    @unittest.skipUnless(FIVE, "no meter-change golden")
    def test_meter_change_reads_as_the_song_has_it(self):
        data = project_data(FIVE)
        times, _keys = read_signatures(data)
        self.assertEqual([[t.numerator, t.denominator] for t in times], _goldens.fact("meter-song", "meters"))
        self.assertEqual(meter(data).bar(times[1].tick), float(_goldens.fact("meter-song", "change_bar")))


@_goldens.needs(*LIST_KEYS)
class SignatureListTest(unittest.TestCase):
    """Logic's own Signature List creates and edits on the blank project: a meter change on the
    bar line after the playhead, a key change at the playhead, each field one save."""

    def test_each_save_reads_its_events(self):
        for key in LIST_KEYS:
            data = project_data(_goldens.path(key))
            times, keys = read_signatures(data)
            with self.subTest(key=key):
                self.assertEqual([[t.numerator, t.denominator] for t in times], _goldens.fact(key, "meters"))
                self.assertEqual([t.tick for t in times], _goldens.fact(key, "meter_ticks"))
                self.assertEqual([k.number for k in keys], _goldens.fact(key, "keys"))
                self.assertEqual([k.tick for k in keys], _goldens.fact(key, "key_ticks"))
                if _goldens.fact(key, "key_names"):
                    self.assertEqual([k.name for k in keys], _goldens.fact(key, "key_names"))
                if _goldens.fact(key, "change_bar"):
                    self.assertEqual(meter(data).bar(times[1].tick), float(_goldens.fact(key, "change_bar")))


if __name__ == "__main__":
    unittest.main()
