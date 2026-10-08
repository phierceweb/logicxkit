"""The metronome's Klopfgeist is not an insert of the user's: `project` leaves it out on the one
channel the Environment's Click object is bound to, and lists a Klopfgeist chosen on a track."""

import unittest

import _goldens
import _paths  # noqa: F401
from logicxkit.logic.services.project.project import analyze, metronome_channel
from logicxkit.logicx import project_data

BLANK = "inserts-native-logic"              # Logic's blank project: Klopfgeist on Inst 2, the metronome's
CHOSEN = "instrument-klopfgeist-logic"      # Klopfgeist chosen on the Inst 1 track as well
FLAT = "stack-convert-holding-folder-after-logic"   # the flat list is the guess without a track count


def _count(key: str) -> int:
    from logicxkit.logic.services.project.project import project_metadata
    return project_metadata(_goldens.path(key))["tracks"]


@_goldens.needs(BLANK, CHOSEN, FLAT)
class MetronomeChannelTest(unittest.TestCase):
    def test_the_click_object_is_bound_to_the_metronome_channel(self):
        self.assertEqual(metronome_channel(project_data(_goldens.path(BLANK))), "Inst 2")
        self.assertEqual(metronome_channel(project_data(_goldens.path(CHOSEN))), "Inst 2")

    def test_the_track_count_tells_the_arrange_rows_from_the_mixer_list(self):
        """On this save the mixer-order list is the guess without a count and carries the Click
        object; with the count the Click has no row and its Inst 1 is the metronome's."""
        data = project_data(_goldens.path(FLAT))
        self.assertEqual(metronome_channel(data, _count(FLAT)), "Inst 1")
        chains = {c["label"]: [n for n, _p in c["chain"]] for c in analyze(data, track_count=_count(FLAT))["channels"]}
        self.assertNotIn("Klopfgeist", chains.get("Inst 1", []))

    def test_the_metronomes_klopfgeist_is_left_out_and_a_chosen_one_listed(self):
        def klopfgeists(key):
            return {c["label"] for c in analyze(project_data(_goldens.path(key)))["channels"]
                    if any(name == "Klopfgeist" for name, _preset in c["chain"])}
        self.assertEqual(klopfgeists(BLANK), set())
        self.assertEqual(klopfgeists(CHOSEN), {"Inst 1"})


if __name__ == "__main__":
    unittest.main()
