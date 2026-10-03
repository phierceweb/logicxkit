"""One source slot fanned out onto a folder stack's members: the write reproduced from its
inputs and held to Logic's re-save of it (2026-09-21). Skips without the owner's files."""

import plistlib
import unittest
from argparse import Namespace

import _goldens
from logicxkit.logic._apply import _targets
from logicxkit.logic._edit import owner_by_label
from logicxkit.logic.services.mixer.mixer import channel_formats
from logicxkit.logic.services.mixer.slot_width import slot_format
from logicxkit.logic.services.stream.stream import HEADER
from logicxkit.logic.services.mixer.plugins import plugin_identity
from logicxkit.logic.services.mixer.transplant import channel_slots, transplant
from logicxkit.logicx import project_data

KEYS = ("transplant-fanout-source", "autoalign-donor", "transplant-fanout-mine", "transplant-fanout-logic")
STACK, SRC_LABEL = "Drums", "Audio 2"
ID_WINDOW, ID_TAIL = 20, 4


def _count(key: str) -> int:
    with open(_goldens.path(key) / "Alternatives" / "000" / "MetaData.plist", "rb") as f:
        return plistlib.load(f)["NumberOfTracks"]


def _members(data: bytes, count: int) -> list[str]:
    return [dst for dst, _src in _targets(Namespace(channel=None, stack=[f"{STACK}={SRC_LABEL}"]), data, count)]


def _drum_slots(data: bytes, labels: list[str]) -> list[bytes]:
    out = []
    for label in labels:
        slots = channel_slots(data, owner_by_label(data, label))
        assert len(slots) == 1, f"{label} carries {len(slots)} slots"
        out.append(slots[0].raw)
    return out


@_goldens.needs(*KEYS)
class FanOutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = project_data(_goldens.path("transplant-fanout-source"))
        cls.donor = project_data(_goldens.path("autoalign-donor"))
        cls.mine = project_data(_goldens.path("transplant-fanout-mine"))
        cls.logic = project_data(_goldens.path("transplant-fanout-logic"))
        cls.count = _count("transplant-fanout-source")
        cls.labels = _members(cls.source, cls.count)

    def test_the_stack_names_the_members_the_manifest_counts(self):
        self.assertEqual(len(self.labels), _goldens.fact("transplant-fanout-source", "members"))

    def test_the_write_is_reproduced_from_its_inputs(self):
        data, src_owner = self.source, owner_by_label(self.donor, SRC_LABEL)
        for label in self.labels:
            data, _report = transplant(self.donor, data, src_owner=src_owner,
                                       dst_owner=owner_by_label(data, label), fan_out=True)
        self.assertEqual(data, self.mine)

    def test_each_member_carries_one_mono_third_party_slot_with_its_own_id(self):
        for name, data in (("mine", self.mine), ("logic", self.logic)):
            with self.subTest(name):
                slots = _drum_slots(data, self.labels)
                formats = channel_formats(data)
                self.assertTrue(all(formats[owner_by_label(data, label)] == 1 for label in self.labels))
                self.assertTrue(all(slot_format(raw) == 1 for raw in slots))
                self.assertEqual({plugin_identity(raw[HEADER:])[0] for raw in slots}, {"au"})
                ids = {raw[-ID_WINDOW:-ID_TAIL] for raw in slots}
                self.assertEqual(len(ids), _goldens.fact(f"transplant-fanout-{name}", "distinct_ids"))

    def test_logic_re_saved_every_slot_as_written(self):
        self.assertEqual(_drum_slots(self.logic, self.labels), _drum_slots(self.mine, self.labels))


if __name__ == "__main__":
    unittest.main()
