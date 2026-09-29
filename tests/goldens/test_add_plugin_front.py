"""A third-party plug-in from the library into slot 1 of every member of a folder stack, in
front of the chains they keep: the write reproduced from its inputs and held to Logic's
re-save (2026-09-21). Skips without the owner's files."""

import plistlib
import unittest
from argparse import Namespace

import _goldens
from logicxkit.logic._add_plugin_cmd import _channels
from logicxkit.logic._edit import owner_by_label
from logicxkit.logic.services.add_plugin import add_plugin
from logicxkit.logic.services.insert import HEADER
from logicxkit.logic.services.plugin_library import find_donor, load_library
from logicxkit.logic.services.transplant import channel_slots, id_offsets, slot_class_version
from logicxkit.logicx import project_data
from logicxkit.utils.data import data_dirs

KEYS = ("addplugin-front-source", "addplugin-front-mine", "addplugin-front-logic")
STACK, PLUGIN = "Drums", "Auto-Align 2"
TOKEN_AT = 76


def _count(key: str) -> int:
    with open(_goldens.path(key) / "Alternatives" / "000" / "MetaData.plist", "rb") as f:
        return plistlib.load(f)["NumberOfTracks"]


LABEL_AT = 14                    # payload +14: the preset label, which Logic fills on load


def _without_token(raw: bytes) -> bytes:
    """The new slot without the two fields Logic rewrites on load: the empty label (filled
    with the preset name) and the +76 token."""
    start, end = HEADER + LABEL_AT, HEADER + TOKEN_AT + 4
    return raw[:start] + bytes(end - start) + raw[end:]


@_goldens.needs(*KEYS)
class FrontTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not any(d.matches(PLUGIN) for d in load_library(data_dirs("donors"))):
            raise unittest.SkipTest(f"the donor library has no {PLUGIN} (the data root's harvest)")
        cls.source = project_data(_goldens.path("addplugin-front-source"))
        cls.mine = project_data(_goldens.path("addplugin-front-mine"))
        cls.logic = project_data(_goldens.path("addplugin-front-logic"))
        cls.labels = _channels(Namespace(channel=None, stack=[STACK]), cls.source, _count("addplugin-front-source"))

    def test_the_write_is_reproduced_from_its_inputs(self):
        donors = load_library(data_dirs("donors"))
        data = self.source
        for label in self.labels:
            owner = owner_by_label(data, label)
            donor = find_donor(donors, PLUGIN, width=1, version=slot_class_version(data))
            offsets = id_offsets(data, donor.raw) or tuple(donor.id_offsets)
            data, _ = add_plugin(data, owner, donor.raw, at=1, id_offsets=offsets, type_id=donor.type_id)
        self.assertEqual(data, self.mine)

    def test_every_member_leads_with_the_plug_in_and_keeps_its_chain(self):
        for label in self.labels:
            with self.subTest(label):
                before = [r.raw for r in channel_slots(self.source, owner_by_label(self.source, label))]
                after = [r.raw for r in channel_slots(self.mine, owner_by_label(self.mine, label))]
                self.assertEqual(len(after), len(before) + 1)
                self.assertEqual([r[HEADER + 200:] for r in after[1:]], [r[HEADER + 200:] for r in before])

    def test_logic_kept_every_slot_but_the_new_ones_token(self):
        """Logic's own plug-ins come back byte for byte. A kept third-party slot keeps its key,
        index, size, identity and id; its state is the plug-in's to rewrite — smart:gate
        re-serialised a quarter of its 463 KB on load."""
        from logicxkit.logic.services.plugins import plugin_identity
        for label in self.labels:
            with self.subTest(label):
                mine = [r.raw for r in channel_slots(self.mine, owner_by_label(self.mine, label))]
                logic = [r.raw for r in channel_slots(self.logic, owner_by_label(self.logic, label))]
                self.assertEqual(_without_token(mine[0]), _without_token(logic[0]))
                self.assertEqual(len(mine), len(logic))
                for a, b in zip(mine[1:], logic[1:], strict=True):
                    identity = plugin_identity(a[HEADER:])
                    if identity and identity[0] == "native":
                        self.assertEqual(a, b)
                    else:
                        self.assertEqual((len(a), a[:HEADER + 8], identity, a[-20:]),
                                         (len(b), b[:HEADER + 8], plugin_identity(b[HEADER:]), b[-20:]))

    def test_the_ids_are_distinct(self):
        ids = {channel_slots(self.logic, owner_by_label(self.logic, label))[0].raw[-20:-4] for label in self.labels}
        self.assertEqual(len(ids), len(self.labels))


if __name__ == "__main__":
    unittest.main()
