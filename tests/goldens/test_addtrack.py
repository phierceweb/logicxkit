"""Adding a track. Measured against Logic's own adds on 2026-09-01 (those saves are gone); the
real-file golden now holds the output to the invariants every Logic file obeys.

The real-file part of tests/logic/test_addtrack.py; skips without the owner's files."""

import unittest
import _paths
from _data import needs

MIX = _paths.staged("Mix")


@unittest.skipIf(not MIX.exists(), "the staged Mix template is not present")
@needs("logic", "inst-track-12.3.1.json", "aux-track-12.3.1.json")
class MixTemplateAddTest(unittest.TestCase):
    """A real Logic 12.3.1 project: the add must keep every measured invariant."""

    @classmethod
    def setUpClass(cls):
        from collections import Counter

        from _invariants import report
        from logicxkit.logic.services.project import project_metadata
        from logicxkit.logic.services.stacks import read_tracks
        from logicxkit.logicx import project_data
        cls.data = project_data(MIX)
        cls.count = project_metadata(MIX)["tracks"]
        rows = read_tracks(cls.data, cls.count)
        names = Counter(r["name"] for r in rows)
        cls.anchor = [r for r in rows if not r["member"] and not r["grouping"] and names[r["name"]] == 1][-1]
        cls.before = report(cls.data, cls.count)["link_errors"]

    def _check(self, out, report, kind):
        from _invariants import assert_consistent
        from logicxkit.logic.services.stacks import read_tracks
        assert_consistent(self, out, self.count + 1, selected=report["object_id"],
                          link_errors_before=self.before)
        rows = read_tracks(out, self.count + 1)
        self.assertEqual([r["key"] for r in rows], list(range(self.count + 2)))
        new = next(r for r in rows if r["object_id"] == report["object_id"])
        self.assertEqual((new["key"], new["member"], new["label"]),
                         (self.anchor["key"] + 1, False, report["label"]))
        self.assertTrue(new["label"].startswith("Audio " if kind == "audio" else "Inst "))

    def test_an_audio_track(self):
        from logicxkit.logic.services.addtrack import add_audio_track
        out, report = add_audio_track(self.data, name="Second Audio", after=self.anchor["object_id"],
                                      track_count=self.count)
        self.assertEqual(report["input"], "Input 1")
        self._check(out, report, "audio")

    def test_an_instrument_track_shifts_every_later_owner(self):
        from logicxkit.logic.services.addtrack import add_track
        from logicxkit.logic.services.binding import channels
        out, report = add_track(self.data, name="Second Inst", after=self.anchor["object_id"],
                                kind="instrument", track_count=self.count)
        self._check(out, report, "instrument")
        before, after = channels(self.data), channels(out)
        self.assertEqual(len(after), len(before) + 1)
        for owner, chan in before.items():
            if owner >= report["owner"] and not chan.label.startswith("Inst "):
                self.assertEqual(after[owner + 1].label, chan.label)


if __name__ == "__main__":
    unittest.main()
