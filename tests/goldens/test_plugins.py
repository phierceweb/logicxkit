"""Plug-in references on Logic's own saves: eight native inserts, every one Apple's."""

import unittest
import _goldens
from logicxkit.logic.services.mixer.plugins import project_plugins, verdict
from logicxkit.logicx import project_data


@_goldens.needs("inserts-native-all-logic")
class NativeInsertsTest(unittest.TestCase):
    def test_every_insert_is_named_and_apple(self):
        refs = [r for r in project_plugins(project_data(_goldens.path("inserts-native-all-logic")))
                if r.channel == _goldens.fact("inserts-native-all-logic", "channel")]
        self.assertEqual([r.name for r in refs], _goldens.fact("inserts-native-all-logic", "inserts"))
        self.assertTrue(all(r.native for r in refs))
        self.assertTrue(verdict(refs, installed=set()).clean)


if __name__ == "__main__":
    unittest.main()
