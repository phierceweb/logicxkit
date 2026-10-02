"""Writing sends: `UCuA` keys 0-2, cloned from a send the project already carries.

A new send lands right after its channel's `OCuA` in key order, before the slots (key 4+).
Only the measured fields are set: owner, key, `+4`, `+20`, a fresh instance UUID at `+44`
and the target `Bus N` channel's UUID at `+60`; a copy's level bytes ride along from its source.

The real-file part of tests/logic/test_sends_write.py; skips without the owner's files."""

import unittest
import _goldens
import _paths
from logicxkit.logic.services.stream import project_records
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


@_goldens.needs("send-level-2-logic", "send-two-base-3-logic")
class AddedSendSettingsTest(unittest.TestCase):
    """Logic's second send, added beside one at -16.8 dB: -inf, post pan, on. Ours from the same
    project carries the same setting bytes."""

    def test_the_settings_match_logics_own_second_send(self):
        from logicxkit.logic.services.stream import HEADER
        from logicxkit.logicx import project_data
        before, logic = (project_data(_goldens.path(k)) for k in ("send-level-2-logic", "send-two-base-3-logic"))
        (owner, (first,)), = read_sends(before).items()
        ours, report = add_send(before, owner=owner, bus=first.bus + 1)
        mine = next(s for s in read_sends(ours)[owner] if s.key == report["key"])
        theirs = next(s for s in read_sends(logic)[owner] if s.bus == first.bus + 1)
        settings = lambda s: s.raw[HEADER + 16:HEADER + 20] + s.raw[HEADER + 22:HEADER + 23] + s.raw[HEADER + 24:HEADER + 28]  # noqa: E731
        self.assertEqual(settings(mine), settings(theirs))
        self.assertNotEqual(settings(mine), settings(first))


@_goldens.needs("send-packaged-ours", "send-packaged-resave-logic")
class LogicResavedPackagedSendTest(unittest.TestCase):
    """A send added to a project that had none to clone: the packaged template, re-saved."""

    def test_logic_kept_the_send_and_its_channel(self):
        from logicxkit.logic.services.channel_alloc import is_mixer_record
        from logicxkit.logic.services.stream import project_records
        from logicxkit.logic.services.sends import read_sends
        from logicxkit.logicx import project_data
        ours, logic = (project_data(_goldens.path(k)) for k in ("send-packaged-ours", "send-packaged-resave-logic"))
        owner = _goldens.fact("send-packaged-ours", "owner")
        (mine,), (theirs,) = read_sends(ours)[owner], read_sends(logic)[owner]
        self.assertEqual((mine.bus, mine.level), (_goldens.fact("send-packaged-ours", "bus"), _goldens.fact("send-packaged-ours", "level_byte")))
        self.assertEqual(mine.raw, theirs.raw)
        strip = lambda data: next(r.raw for r in project_records(data) if is_mixer_record(r) and r.owner == owner)  # noqa: E731
        self.assertEqual(strip(ours), strip(logic))


if __name__ == "__main__":
    unittest.main()
