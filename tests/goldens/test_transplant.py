"""Cloning a channel's plugin slots from one project onto another.

Records move verbatim (AU state is opaque) and are re-stamped for the target. Slot keys run
from 4 up to the project's `.cst`-reference key, which differs per session (9/10/12/13).

The real-file part of tests/logic/test_transplant.py; skips without the owner's files."""

import unittest
import _goldens
import _paths
from logicxkit.logic.services.transplant import (
    owner_of,
    transplant,
)



@unittest.skipIf(not _paths.have(_paths.staged("Mix")), "staged Mix template not present")
@_goldens.needs("tracking-template")
class GoldenTransplantTest(unittest.TestCase):
    def test_guitar_amp_sim_lands_on_the_tracking_template(self):
        from logicxkit.logic.services.manifest import manifest_from_bytes
        from logicxkit.logicx import project_data
        src = project_data(_paths.staged("Mix"))
        dst = project_data(_goldens.path("tracking-template"))
        s, d = owner_of(src, "Audio 20"), owner_of(dst, "Audio 20")
        out, report = transplant(src, dst, src_owner=s, dst_owner=d)
        row = next(c for c in manifest_from_bytes(out)["channels"] if c["label"] == "Audio 20")
        self.assertEqual([p for p, _ in row["chain"]], ["Soldano"])
        self.assertEqual(report["slots"], 1)


class LegacyBaseWordTest(unittest.TestCase):
    """Logic's verdict on the base word: the legacy song, rebased, and its re-save."""

    def test_legacy_song_and_logics_verdict(self):
        from logicxkit.logic.services.binding import channels
        from logicxkit.logic.services.insert import project_records
        from logicxkit.logic.services.sends import is_send
        from logicxkit.logic.services.slotkeys import channel_bases, rebase
        from logicxkit.logicx import project_data
        legacy, verdict = _goldens.path("legacy-song"), _goldens.path("legacy-base4-logic")
        if legacy is None or verdict is None:
            self.skipTest("no legacy song golden or its base-4 re-save")
        data = project_data(legacy)
        self.assertEqual(set(channel_bases(data)), {2})
        self.assertEqual(set(channel_bases(rebase(data)[0])), {4})
        saved = project_data(verdict)
        self.assertEqual(set(channel_bases(saved)), {4})
        ch = channels(saved)
        vox = next(o for o, c in ch.items() if c.label == _goldens.fact("legacy-base4-logic", "three_send_channel"))
        recs = [r for r in project_records(saved) if r.owner == vox and r.tag == b"UCuA"]
        self.assertEqual(sorted(r.key for r in recs if is_send(r)), [0, 1, 2])
        self.assertEqual(sorted(r.key for r in recs if not is_send(r) and r.key < 10), [4, 5])


if __name__ == "__main__":
    unittest.main()
