"""Session Player regions: the settings JSON Logic keeps in the region's `MneG` record, one
control moved per save, and the generated notes in the region's sequence."""

import unittest
import _goldens
from logicxkit.logic.services.regions.sessionplayer import read_session_players
from logicxkit.logicx import project_data


def _one(key: str):
    (sp,) = read_session_players(project_data(_goldens.path(key)))
    return sp


@_goldens.needs("sessionplayer-track-logic")
class TrackTest(unittest.TestCase):
    def test_the_new_track_and_its_generated_region(self):
        sp = _one("sessionplayer-track-logic")
        facts = _goldens.entry("sessionplayer-track-logic")["facts"]
        self.assertEqual((sp.character, sp.preset, sp.region), (facts["character"], facts["preset"], facts["region"]))
        self.assertEqual((sp.settings["rComp"], sp.settings["fillsAmount"], sp.settings["swing"]), (facts["complexity"], facts["fills"], facts["swing"]))
        self.assertEqual((sp.notes, sp.generated_bars), (facts["notes"], facts["bars"]))
        self.assertFalse(sp.settings["PresetDirty"])


class OneControlPerSaveTest(unittest.TestCase):
    def _check(self, key: str):
        sp = _one(key)
        facts = _goldens.entry(key)["facts"]
        self.assertEqual((sp.complexity, sp.fills, sp.swing), (facts["complexity"], facts["fills"], facts["swing"]))

    @_goldens.needs("sessionplayer-complexity-logic")
    def test_complexity(self):
        self._check("sessionplayer-complexity-logic")

    @_goldens.needs("sessionplayer-fills-logic")
    def test_fill_amount(self):
        self._check("sessionplayer-fills-logic")

    @_goldens.needs("sessionplayer-swing-logic")
    def test_swing(self):
        self._check("sessionplayer-swing-logic")


class PlayerAndTypeTest(unittest.TestCase):
    """The picker's style row changes the player; its Type popup changes the player family and,
    with Change Patch on, the patch. Both land in the region's JSON as CharacterIdentifier."""

    def _check(self, key: str):
        sp = _one(key)
        facts = _goldens.entry(key)["facts"]
        self.assertEqual((sp.character, sp.preset, sp.region), (facts["character"], facts["preset"], facts["region"]))
        self.assertEqual((sp.notes, sp.generated_bars), (facts["notes"], facts["bars"]))

    @_goldens.needs("sessionplayer-player-logic")
    def test_another_player_of_the_same_type(self):
        self._check("sessionplayer-player-logic")

    @_goldens.needs("sessionplayer-type-logic")
    def test_another_player_type(self):
        self._check("sessionplayer-type-logic")


if __name__ == "__main__":
    unittest.main()
