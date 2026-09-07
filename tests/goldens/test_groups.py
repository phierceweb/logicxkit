"""Logic groups: the group triple, the member events, the object's group number and the
registry pair. Synthetic projects prove the structure; the goldens hold the writers to
Logic's own single-change saves when those are on hand.

The real-file part of tests/logic/test_groups.py; skips without the owner's files."""

import unittest
from pathlib import Path
import _goldens
import _paths  # noqa: F401
from logicxkit.logic.services.environment import channel_objects
from logicxkit.logic.services.groups import (
    FLAGS,
    assign,
    create_group,
    group_errors,
    group_of,
    read_groups,
    set_group,
    settings_of,
)
from logicxkit.logic.services.insert import HEADER, project_records
from logicxkit.logic.services.registry import group_entries
from _data import needs

SAVES = next(iter(sorted((_goldens.path("controlbar-saves") or _paths.RESOURCES / "missing").glob("53-group1-audio5.logicx"))), None)
TEMPLATE = _paths.staged("Mix")
def _load(path: Path) -> bytes:
    return sorted(path.glob("Alternatives/*/ProjectData"))[0].read_bytes()


@unittest.skipIf(SAVES is None, "the group single-change saves are not present")
@needs("logic", "group-12.3.1.json")
class GoldenTest(unittest.TestCase):
    """Logic's own saves, 2026-09-05: a group made on one track (53), a second member (55),
    a second group (56), a rename with three boxes changed (62), and the boxes toggled through
    (66, 80). The writer's triple, numbers and registry pair must equal Logic's; the triple id
    and the UUIDs are Logic's choice."""

    @classmethod
    def setUpClass(cls):
        d = SAVES.parent
        cls.base = _load(next(d.glob("cb-51*.logicx")))
        cls.saves = {n: _load(next(d.glob(f"{n}-*.logicx"))) for n in (53, 55, 56, 62, 66, 80)}
        objs = {o.name: oid for oid, o in channel_objects(cls.saves[53]).items()}
        cls.a5, cls.a6, cls.a7 = objs["Audio 5"], objs["Audio 6"], objs["Audio 7"]

    def _same(self, mine: bytes, logic: bytes):
        mr, lr = project_records(mine), project_records(logic)
        starts = [g.start for g in read_groups(mine)]
        self.assertEqual(starts, [g.start for g in read_groups(logic)])
        for start in starts:
            for k in range(3):
                a, b = bytearray(mr[start + k].raw), bytearray(lr[start + k].raw)
                if k in (0, 2):
                    a[14:16] = b[14:16] = b"\0\0"
                if k == 0:
                    a[HEADER + 8:HEADER + 12] = b[HEADER + 8:HEADER + 12] = bytes(4)
                self.assertEqual(a, b, f"record {start + k}")
        self.assertEqual(group_of(mine), group_of(logic))
        gm = next(r.raw[HEADER:] for r in mr if r.tag == b"gnoS")
        gl = next(r.raw[HEADER:] for r in lr if r.tag == b"gnoS")
        for stride in (24, 16):
            self.assertEqual(group_entries(gm, stride), group_entries(gl, stride), stride)
        self.assertEqual(group_errors(mine), [])

    def test_a_group_made_on_one_track(self):
        self._same(create_group(self.base, members=[self.a5])[0], self.saves[53])

    def test_a_second_member(self):
        self._same(assign(self.saves[53], self.a6, 1), self.saves[55])

    def test_a_second_group(self):
        self._same(create_group(self.saves[55], members=[self.a7])[0], self.saves[56])

    def test_a_rename_with_boxes_changed(self):
        want = settings_of(read_groups(self.saves[62])[0].flags)
        self.assertEqual(want, ["Mute", "Send 1", "Color", "Automation Mode"])
        self._same(set_group(self.saves[56], 1, name="Drums", settings=want), self.saves[62])

    def test_the_faders_swapped_for_solo_and_pan(self):
        self._same(set_group(self.saves[62], 1, settings=settings_of(read_groups(self.saves[66])[0].flags)),
                   self.saves[66])

    def test_every_box_on(self):
        flags = read_groups(self.saves[80])[0].flags
        self.assertEqual(len(settings_of(flags)), len(FLAGS) - 3)          # Volume, Mute, Automation Mode off
        self._same(set_group(self.saves[62], 1, settings=settings_of(flags)), self.saves[80])


@unittest.skipIf(not TEMPLATE.exists(), "the Mix template is not present")
class TemplateGroupsTest(unittest.TestCase):
    def test_the_templates_groups_read_with_their_members(self):
        from logicxkit.logicx import project_data
        data = project_data(TEMPLATE)
        groups = read_groups(data)
        self.assertGreaterEqual(len(groups), 2)
        objs = channel_objects(data)
        named = {g.name: [objs[m].name for m in g.members] for g in groups}
        self.assertEqual(named["OH"], ["OH L", "OH R"])
        self.assertEqual(group_errors(data), [])

    def test_a_members_events_are_rebuilt_from_its_channel_levels(self):
        """The template's overheads sit off unity, and their Volume events carry that."""
        from logicxkit.logicx import project_data
        from logicxkit.logic.services.groups import _events_for, _values
        data = project_data(TEMPLATE)
        oh = next(g for g in read_groups(data) if g.name == "OH")
        raw = project_records(data)[oh.start + 2].raw[HEADER:]
        self.assertEqual(_events_for(oh.flags, oh.members, _values(data)), raw[:-16])


if __name__ == "__main__":
    unittest.main()
