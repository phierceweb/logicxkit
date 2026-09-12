"""Leaving a group, against Logic's own save of one member set to No Group."""

import unittest

import _goldens
from _data import needs
from logicxkit.logic.services.groups import assign, group_of, read_groups
from logicxkit.logic.services.recdiff import diff_records
from logicxkit.logic.services.stacks import read_tracks
from logicxkit.logicx import project_data


@_goldens.needs("group-drums-logic", "group-leave-logic")
class LogicLeaveTest(unittest.TestCase):
    def setUp(self):
        self.before = project_data(_goldens.path("group-drums-logic"))
        self.after = project_data(_goldens.path("group-leave-logic"))
        self.names = {r["object_id"]: r["name"] for r in read_tracks(self.after, 3)}

    def test_the_reader_sees_the_member_gone(self):
        (g,) = read_groups(self.after)
        self.assertEqual([self.names[m] for m in g.members], _goldens.fact("group-leave-logic", "members"))
        self.assertNotIn(_goldens.fact("group-leave-logic", "left"), {self.names.get(k) for k in group_of(self.after)})

    # The goldens gate opens on the public corpus; writing also needs the untracked data root.
    @needs("logic", "group-12.3.1.json")
    def test_our_leave_matches_logics_save(self):
        left = next(o for o, n in self.names.items() if n == _goldens.fact("group-leave-logic", "left"))
        ours = assign(self.before, left, 0)
        (g,) = read_groups(ours)
        self.assertEqual([self.names[m] for m in g.members], _goldens.fact("group-leave-logic", "members"))
        d = diff_records(ours, self.after)
        self.assertFalse(d.added or d.removed)
        # Audio 1 was clicked alone before it left: the object selected flag (+116) and the row
        # bytes +76/+79 are that selection, not the leave
        rest = [(c.tag, c.offsets) for c in d.changed if c.tag not in (b"gnoS", b"qeSM")]
        self.assertTrue(all(t == b"ivnE" and o == [116] or t == b"karT" and set(o) <= {76, 79} for t, o in rest), rest)
