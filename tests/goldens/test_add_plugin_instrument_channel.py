"""`add-plugin` appending to an instrument channel Logic laid out itself: on Logic's own save
of an instrument with one effect the effect sits two keys under the reference, where the
headroom grow must leave it; the append lands after it, once (`instrument-es2-over-chromaglow-logic`)."""

import unittest

import _goldens
from logicxkit.logic._edit import owner_by_label
from logicxkit.logic.services.mixer.add_plugin import add_plugin
from logicxkit.logic.services.mixer.plugin_library import find_donor, load_library
from logicxkit.logic.services.mixer.plugins import project_plugins
from logicxkit.logic.services.mixer.transplant import channel_slots, slot_class_version
from logicxkit.logic.services.stream.validate import validate_project
from logicxkit.logicx import project_data
from logicxkit.utils.data import PACKAGED

KEY = "instrument-es2-over-chromaglow-logic"
LABEL = "Inst 1"


@_goldens.needs(KEY)
class AppendAfterLogicsEffectTest(unittest.TestCase):
    def test_the_effect_is_kept_once_and_the_new_slot_follows_it(self):
        before = project_data(_goldens.path(KEY))
        owner = owner_by_label(before, LABEL)
        donor = find_donor(load_library([PACKAGED / "donors"]), "Channel EQ", width=None, version=slot_class_version(before))
        out, report = add_plugin(before, owner, donor.raw, type_id=donor.type_id)
        names = [(r.key, r.name) for r in project_plugins(out) if r.channel == LABEL and not r.midi]
        keys = [r.key for r in channel_slots(out, owner)]
        self.assertEqual([n for _k, n in names], ["ES2", "ChromaGlow", "Channel EQ"])
        self.assertEqual(keys, sorted(keys))
        self.assertEqual(len(set(keys)), 3)
        self.assertEqual(report["moved"], [])
        self.assertEqual(validate_project(out), [])


if __name__ == "__main__":
    unittest.main()
