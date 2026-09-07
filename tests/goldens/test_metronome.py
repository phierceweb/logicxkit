"""Metronome and Recording project settings against Logic's own saves, one change each."""

import unittest

import _goldens
from logicxkit.logic.services.metronome import BITS, PREROLL, copy_metronome, read_metronome, set_metronome
from logicxkit.logic.services.modes import read_modes
from logicxkit.logic.services.recdiff import diff_records, load_project_data

KEYS = ["metronome-simple-off-logic", "metronome-click-recording-off-logic", "metronome-click-playing-off-logic",
        "metronome-polyphonic-on-logic", "metronome-rows-base-logic", "metronome-rows-flipped-logic",
        "metronome-division-row-logic", "metronome-group-velocity-logic", "metronome-beat-note-logic",
        "recording-colorize-on-logic", "recording-tempo-change-on-logic", "recording-reduction-off-logic",
        "recording-erase-off-logic", "recording-preroll-on-logic", "recording-preroll-10s-logic",
        "recording-count-in-2-bars-logic", "grid-on-logic", "grid-off-logic", "click-button-on-logic"]
PATHS = {k: _goldens.path(k) for k in KEYS}
BASE = _goldens.path("modes-base-b-logic")


def _data(key):
    return load_project_data(PATHS[key])


@unittest.skipUnless(all(PATHS.values()) and BASE, "no metronome saves")
class GoldenMetronomeTest(unittest.TestCase):
    def test_each_save_reads_as_the_change_it_recorded(self):
        for key in KEYS:
            facts = _goldens.entry(key).get("facts", {})
            state, modes = read_metronome(_data(key)), read_modes(_data(key))
            with self.subTest(key=key):
                for name in facts.get("on", []):
                    self.assertTrue(state[name], name)
                for name in facts.get("off", []):
                    self.assertFalse(state[name], name)
                if "rows_on" in facts:
                    on = {n for n, row in state["MIDI click"].items() if row["on"]}
                    self.assertEqual(on, set(facts["rows_on"]))
                if "division" in facts:
                    row = state["MIDI click"]["Division"]
                    self.assertEqual({k: row[k] for k in facts["division"]}, facts["division"])
                if "group_velocity" in facts:
                    self.assertEqual(state["Klopfgeist"]["Group"]["velocity"], facts["group_velocity"])
                if "beat_note" in facts:
                    self.assertEqual(state["Klopfgeist"]["Beat"]["note"], facts["beat_note"])
                if "preroll" in facts:
                    self.assertEqual(state[PREROLL], facts["preroll"])
                if "count_in" in facts:
                    self.assertEqual(modes["Count-in"], facts["count_in"])
                if "grid" in facts:
                    self.assertEqual(modes["Use Musical Grid"], facts["grid"])

    def test_button_and_box_share_the_click_bit(self):
        self.assertTrue(read_modes(_data("click-button-on-logic"))["Metronome Click"])
        self.assertTrue(read_metronome(_data("click-button-on-logic"))["Click while playing"])
        self.assertFalse(read_modes(_data("metronome-click-playing-off-logic"))["Metronome Click"])

    def test_our_flag_writes_land_where_logic_put_them(self):
        """Each pane save against the one before it: our write of that one change over the
        earlier save differs from Logic's save only at the bytes Logic churns on any change."""
        pairs = [("metronome-simple-off-logic", "metronome-click-recording-off-logic", {"Click while recording": False}),
                 ("metronome-click-recording-off-logic", "metronome-click-playing-off-logic", {"Click while playing": False}),
                 ("metronome-click-playing-off-logic", "metronome-polyphonic-on-logic", {"Polyphonic clicks": True}),
                 ("recording-colorize-on-logic", "recording-tempo-change-on-logic", {"Allow tempo change recording": True}),
                 ("recording-tempo-change-on-logic", "recording-reduction-off-logic", {"MIDI data reduction": False}),
                 ("recording-reduction-off-logic", "recording-erase-off-logic", {"Automatically erase duplicates": False}),
                 ("recording-erase-off-logic", "recording-preroll-on-logic", {"Pre-roll instead of count-in": True}),
                 ("recording-preroll-on-logic", "recording-preroll-10s-logic", {PREROLL: 10.0})]
        for before, after, want in pairs:
            ours = set_metronome(_data(before), want)
            d = diff_records(ours, _data(after))
            song = [c for c in d.changed if c.tag == b"gnoS"]
            with self.subTest(after=after):
                self.assertFalse(d.added or d.removed)
                self.assertTrue(all(set(c.offsets) <= {14, 15, 173, 258} for c in song), [c.offsets for c in song])

    def test_copy_carries_flags_rows_and_click_object(self):
        src = _data("metronome-division-row-logic")
        out, state = copy_metronome(src, _data("modes-base-b-logic") if False else load_project_data(BASE))
        self.assertEqual(state, read_metronome(out))
        self.assertEqual(state["MIDI click"], read_metronome(src)["MIDI click"])
        self.assertEqual(state["Klopfgeist"], read_metronome(src)["Klopfgeist"])
        for name in BITS:
            self.assertEqual(state[name], read_metronome(src)[name], name)


if __name__ == "__main__":
    unittest.main()
