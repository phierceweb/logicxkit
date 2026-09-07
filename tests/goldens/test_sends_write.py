"""Writing sends: `UCuA` keys 0-2, cloned from a send the project already carries.

A new send lands right after its channel's `OCuA` in key order, before the slots (key 4+).
Only the measured fields are set: owner, key, `+4`, `+20`, a fresh instance UUID at `+44`
and the target `Bus N` channel's UUID at `+60`; the level bytes ride along from the template.

The real-file part of tests/logic/test_sends_write.py; skips without the owner's files."""

import unittest
import _paths
from logicxkit.logic.services.insert import project_records
from logicxkit.logic.services.sends import read_sends
from logicxkit.logic.services.sends_write import add_send, copy_sends, remove_sends

MIX = _paths.staged("Mix")


@unittest.skipIf(not MIX.exists(), "the staged Mix template is not present")
class MixTemplateSendTest(unittest.TestCase):
    """A send on a real project: cloned from one of its own, placed after the channel record,
    flagged on the channel, and the whole file still consistent."""

    @classmethod
    def setUpClass(cls):
        from collections import Counter

        from logicxkit.logic.services.project import project_metadata
        from logicxkit.logic.services.stacks import read_tracks
        from logicxkit.logicx import project_data
        cls.data = project_data(MIX)
        cls.count = project_metadata(MIX)["tracks"]
        rows = read_tracks(cls.data, cls.count)
        names = Counter(r["name"] for r in rows)
        cls.owner = [r for r in rows if not r["member"] and not r["grouping"] and names[r["name"]] == 1
                     and r["owner"] not in read_sends(cls.data)][-1]["owner"]
        cls.bus = sorted({s.bus for ss in read_sends(cls.data).values() for s in ss})[-1]

    def test_add_then_remove_round_trips_and_stays_consistent(self):
        from _invariants import report
        from logicxkit.logic.services.recdiff import diff_records
        out, rep = add_send(self.data, owner=self.owner, bus=self.bus)
        self.assertEqual((rep["key"], rep["bus"], rep["replaced"]), (0, self.bus, False))
        self.assertEqual([(s.key, s.bus) for s in read_sends(out)[self.owner]], [(0, self.bus)])
        r = report(out, self.count)
        self.assertEqual((r["validate"], r["bad_send_flags"]), ([], []))
        records = project_records(out)
        i = next(i for i, r in enumerate(records) if r.tag == b"OCuA" and r.owner == self.owner)
        self.assertEqual((records[i + 1].tag, records[i + 1].owner, records[i + 1].key), (b"UCuA", self.owner, 0))
        d = diff_records(self.data, out)
        self.assertEqual([(e.tag, e.owner, e.key) for e in d.added], [(b"UCuA", self.owner, 0)])
        self.assertEqual([(c.tag, c.owner) for c in d.changed], [(b"OCuA", self.owner)])   # the flag
        back = remove_sends(out, owner=self.owner)
        self.assertEqual(back, self.data)

    def test_copy_brings_a_channels_set_across(self):
        src_owner, sends = next((o, ss) for o, ss in read_sends(self.data).items() if len(ss) >= 2)
        out, rep = copy_sends(self.data, self.data, src_owner=src_owner, dst_owner=self.owner)
        self.assertEqual(rep["keys"], [s.key for s in sends])
        self.assertEqual([(s.key, s.bus) for s in read_sends(out)[self.owner]],
                         [(s.key, s.bus) for s in sends])
        from _invariants import report
        self.assertEqual(report(out, self.count)["bad_send_flags"], [])


if __name__ == "__main__":
    unittest.main()
