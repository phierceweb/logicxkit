"""Division and key: the song-record bytes and the key event, against Logic's own edits.

The real-file part of tests/logic/test_settings.py; skips without the owner's files."""

import unittest
import _goldens
import _paths
from logicxkit.logic.services.events import events
from logicxkit.logic.services.insert import HEADER, project_records
from logicxkit.logic.services.integrity import require_no_regression
from logicxkit.logic.services.sequence import sequences
from logicxkit.logic.services.settings import read_settings, set_division
from logicxkit.logic.services.signature import KEY_TYPE, read_signatures
from logicxkit.logic.services.signature_write import set_key
from logicxkit.logicx import project_data

SONGS = sorted(p for d in ("mixes", "legacy") for p in (_paths.RESOURCES / d).glob("*/*.logicx"))
THREE, KEY_G, DIV48 = _goldens.path("meter-3-4-logic"), _goldens.path("key-g-logic"), _goldens.path("div-48-logic")
def key_event(data):
    recs = project_records(data)
    return next(e for e in events(recs[sequences(recs)[0].end].raw[HEADER:]) if e.type == KEY_TYPE)


@unittest.skipUnless(SONGS, "no resources copies")
class GoldenTest(unittest.TestCase):
    def test_band_songs_are_sixteenths_in_c(self):
        for song in SONGS:
            s = read_settings(project_data(song))
            self.assertEqual((s["division"], s["key_root"]), (16, "C"), song)
            self.assertIn(s["division_ticks"], (240, 0), song)
            self.assertEqual(read_signatures(project_data(song))[1][0].name, "C major", song)

    def test_set_division(self):
        data = project_data(SONGS[0])
        after = set_division(data, 32)
        require_no_regression(data, after)
        self.assertEqual((read_settings(after)["division"], read_settings(after)["division_ticks"]), (32, 120))
        with self.assertRaises(ValueError):
            set_division(data, 20)

    def test_set_key(self):
        data = project_data(SONGS[0])
        after = set_key(data, "Bb")
        require_no_regression(data, after)
        self.assertEqual(read_signatures(after)[1][0].name, "Bb major")
        self.assertEqual(read_settings(after)["key_root"], "A#")


@unittest.skipUnless(THREE and KEY_G and DIV48, "no Logic settings saves")
class LogicPairTest(unittest.TestCase):
    def test_key_edit_matches_logic(self):
        ours = set_key(project_data(THREE), _goldens.fact("key-g-logic", "key"))
        logic = project_data(KEY_G)
        self.assertEqual(key_event(ours).head[:15], key_event(logic).head[:15])
        self.assertEqual(read_settings(ours)["key_root"], read_settings(logic)["key_root"])

    def test_division_edit_matches_logic(self):
        ours = set_division(project_data(KEY_G), _goldens.fact("div-48-logic", "division"))
        logic = project_data(DIV48)
        self.assertEqual(read_settings(ours), read_settings(logic))
        f = _goldens.entry("div-48-logic")["facts"]
        self.assertEqual(read_settings(logic), {"division": f["division"], "division_index": f["division_index"], "division_ticks": f["division_ticks"], "key_root": f["root"]})


if __name__ == "__main__":
    unittest.main()


KEY_BASE, A_MINOR, E_MINOR = _goldens.path("key-base"), _goldens.path("key-a-minor-logic"), _goldens.path("key-e-minor-logic")


@unittest.skipUnless(KEY_BASE and A_MINOR and E_MINOR, "no Logic minor-key saves")
class MinorKeyTest(unittest.TestCase):
    def test_logics_minor_keys_read_as_named(self):
        for key, path in (("key-a-minor-logic", A_MINOR), ("key-e-minor-logic", E_MINOR)):
            with self.subTest(key):
                sig = read_signatures(project_data(path))[1][0]
                self.assertEqual((sig.name, sig.number), (_goldens.fact(key, "key"), _goldens.fact(key, "number")))
                self.assertEqual(read_settings(project_data(path))["key_root"], _goldens.fact(key, "root"))

    def test_ours_matches_logics_edit(self):
        for key, path in (("key-a-minor-logic", A_MINOR), ("key-e-minor-logic", E_MINOR)):
            with self.subTest(key):
                ours = set_key(project_data(KEY_BASE), _goldens.fact(key, "key"))
                logic = project_data(path)
                self.assertEqual(key_event(ours).head[:15], key_event(logic).head[:15])
                self.assertEqual(read_settings(ours)["key_root"], read_settings(logic)["key_root"])


CHANGES_BASE = _goldens.path("changes-base")
KEY_CHANGE, METER_CHANGE = _goldens.path("key-change-logic"), _goldens.path("meter-change-logic")


@unittest.skipUnless(CHANGES_BASE and KEY_CHANGE and METER_CHANGE, "no Logic signature-change saves")
class SignatureChangesTest(unittest.TestCase):
    """Key and meter changes after bar 1, held against Logic's own."""

    @staticmethod
    def _events(data):
        from logicxkit.logic.services.events import events
        from logicxkit.logic.services.insert import HEADER, project_records
        from logicxkit.logic.services.sequence import sequences
        recs = project_records(data)
        return events(recs[sequences(recs)[0].end].raw[HEADER:])

    @staticmethod
    def _masked(e):
        head = bytes(b & 0x7F if i == 15 else b for i, b in enumerate(e.head))
        head = head[:2] + b"\0\0" + head[4:]                         # Logic's session word, at head +2
        data = e.data[:10] + b"\0\0" + e.data[12:]                  # and again at data +10
        if e.type == 0x30 and e.tick > 38400:
            data = data[:12] + b"\0\0\0\0"                          # a meter change's +12 word is stale in Logic's own
        return head, data, e.lines[1:]

    def test_key_change_matches_logics(self):
        from logicxkit.logic.services.signature_write import add_key_change
        tick, key = _goldens.fact("key-change-logic", "tick"), _goldens.fact("key-change-logic", "key")
        ours = self._events(add_key_change(project_data(CHANGES_BASE), tick, key))
        logic = self._events(project_data(KEY_CHANGE))
        self.assertEqual([self._masked(e) for e in ours], [self._masked(e) for e in logic])
        self.assertEqual([k.name for k in read_signatures(project_data(KEY_CHANGE))[1]], ["C major", f"{key} major"])

    def test_meter_change_matches_logics(self):
        from logicxkit.logic.services.events import BAR_ONE
        from logicxkit.logic.services.signature_write import add_key_change, add_meter_change
        f = _goldens.entry("meter-change-logic")["facts"]
        data = add_key_change(project_data(CHANGES_BASE), f["key_tick"], f["key"])
        ours = self._events(add_meter_change(data, BAR_ONE + (f["bar"] - 1) * 3840, f["numerator"], f["denominator"]))
        logic = self._events(project_data(METER_CHANGE))
        self.assertEqual([self._masked(e) for e in ours], [self._masked(e) for e in logic])
        times = read_signatures(project_data(METER_CHANGE))[0]
        self.assertEqual([(t.numerator, t.denominator) for t in times], [(4, 4), (f["numerator"], f["denominator"])])

    def test_refusals(self):
        from logicxkit.logic.services.events import BAR_ONE
        from logicxkit.logic.services.signature_write import add_key_change, add_meter_change
        base = project_data(CHANGES_BASE)
        with self.assertRaises(ValueError):
            add_meter_change(base, BAR_ONE + 100, 3, 4)                # not on a bar line
        with self.assertRaises(ValueError):
            add_key_change(base, 0, "G")                                # the start, not a change
