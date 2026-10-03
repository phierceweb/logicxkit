"""`add_plugin` against Logic's own appends: the `master-track-*` saves add one plug-in to Audio 1
per save, and the packaged library's donors were harvested from the last of them. Skips
without the public corpus."""

import unittest

import _goldens
from logicxkit.logic._edit import owner_by_label
from logicxkit.logic.services.mixer.add_plugin import add_plugin
from logicxkit.logic.services.mixer.mixer import CHANNEL_TAG
from logicxkit.logic.services.stream.stream import project_records
from logicxkit.logic.services.stream.keyflags import flag_errors
from logicxkit.logic.services.mixer.plugin_library import find_donor, load_library
from logicxkit.logic.services.mixer.transplant import channel_slots, slot_class_version
from logicxkit.logicx import project_data
from logicxkit.utils.data import PACKAGED

LABEL = "Audio 1"
# the library's Multipressor and Adaptive Limiter are these saves' own instances; its Limiter
# comes from an earlier save, so only its instance id differs
STEPS = (("master-track-lpeq-logic", "master-track-multipressor-logic", "Multipressor", True),
         ("master-track-multipressor-logic", "master-track-adaptive-limiter-logic", "Adaptive Limiter", True),
         ("master-track-adaptive-limiter-logic", "master-track-limiter-logic", "Limiter", False))
KEYS = tuple(sorted({k for step in STEPS for k in step[:2]}))
ID_WINDOW, ID_TAIL = 20, 4


def _channel_record(data: bytes, owner: int) -> bytes:
    return max((r.raw for r in project_records(data) if r.tag == CHANNEL_TAG and r.owner == owner), key=len)


def _without_id(raw: bytes) -> bytes:
    return raw[:-ID_WINDOW] + raw[-ID_TAIL:]


@_goldens.needs(*KEYS)
class AppendTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.donors = load_library([PACKAGED / "donors"])      # the same on every machine

    def test_each_save_is_the_previous_one_plus_the_library_plug_in(self):
        for before_key, after_key, plugin, same_instance in STEPS:
            with self.subTest(plugin):
                before, after = project_data(_goldens.path(before_key)), project_data(_goldens.path(after_key))
                owner = owner_by_label(before, LABEL)
                donor = find_donor(self.donors, plugin, width=None, version=slot_class_version(before))
                ours, report = add_plugin(before, owner, donor.raw, type_id=donor.type_id)
                self.assertEqual(report["moved"], [])
                mask = (lambda raw: raw) if same_instance else _without_id
                self.assertEqual([mask(r.raw) for r in channel_slots(ours, owner)],
                                 [mask(r.raw) for r in channel_slots(after, owner_by_label(after, LABEL))])
                self.assertEqual(flag_errors(ours), [])

    def test_the_channel_record_reads_as_logic_wrote_it(self):
        """The key-flag words the insert sets are the ones Logic's own append set — the archive
        records past the reference key move up with the chain, and their flags with them."""
        before_key, after_key, plugin, _same = STEPS[0]
        before, after = project_data(_goldens.path(before_key)), project_data(_goldens.path(after_key))
        owner = owner_by_label(before, LABEL)
        donor = find_donor(self.donors, plugin, width=None, version=slot_class_version(before))
        ours, _ = add_plugin(before, owner, donor.raw, type_id=donor.type_id)
        self.assertEqual(_channel_record(ours, owner), _channel_record(after, owner_by_label(after, LABEL)))


if __name__ == "__main__":
    unittest.main()
