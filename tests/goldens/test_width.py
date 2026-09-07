"""Channel width: two auxes made stereo by us, re-saved by Logic with the width and the
plug-in builds intact — on both templates."""

import unittest

import _goldens
from logicxkit.logic.services.binding import channels
from logicxkit.logic.services.insert import HEADER, STEREO, MONO, channel_formats, find_blocks, project_records, slot_format
from logicxkit.logic.services.recdiff import diff_records, load_project_data

PAIRS = [("width-mix-mine", "width-mix-logic"), ("width-tracking-mine", "width-tracking-logic")]
PATHS = {k: _goldens.path(k) for pair in PAIRS for k in pair}


def _widths(path, labels):
    data = load_project_data(path)
    recs, chans, fmts = project_records(data), channels(data), channel_formats(data)
    out = {}
    for label in labels:
        owner = next(o for o, c in chans.items() if c.label == label)
        slots = [slot_format(r.raw) for r in recs if r.owner == owner and r.tag == b"UCuA" and find_blocks(r.raw[HEADER:])]
        out[label] = (fmts.get(owner), slots)
    return out


@unittest.skipUnless(all(PATHS.values()), "no width saves")
class GoldenWidthTest(unittest.TestCase):
    def test_logic_kept_the_widths_and_the_builds(self):
        for mine, logic in PAIRS:
            facts = _goldens.entry(mine)["facts"]
            labels = facts["stereo"] + facts["mono"]
            ours, theirs = _widths(PATHS[mine], labels), _widths(PATHS[logic], labels)
            with self.subTest(pair=mine):
                self.assertEqual(ours, theirs)
                for label in facts["stereo"]:
                    self.assertEqual(ours[label][0], STEREO)
                    self.assertTrue(ours[label][1] and all(s == STEREO for s in ours[label][1]), label)
                for label in facts["mono"]:
                    self.assertEqual(ours[label][0], MONO)
                d = diff_records(load_project_data(PATHS[mine]), load_project_data(PATHS[logic]))
                self.assertFalse(d.added or d.removed)


if __name__ == "__main__":
    unittest.main()
