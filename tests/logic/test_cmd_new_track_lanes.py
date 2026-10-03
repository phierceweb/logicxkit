"""A track or stack the writers add starts with no automation, whatever lanes the track its
structures are cloned from carries."""

import tempfile
import unittest
from pathlib import Path

import _goldens
from _cli import count, data, written

from logicxkit.logic.services.regions.automation import read_automation

THREE = "tracks-three-audio-logic"          # Audio 1, Audio 2, Audio 3, then the Stereo Out row


def lanes(bundle) -> dict[str, list[tuple[str, int]]]:
    """Track name -> (lane, point count) for every track lane."""
    out: dict[str, list[tuple[str, int]]] = {}
    for a in read_automation(data(bundle), count(bundle)):
        found = [(ln.parameter, len(ln.points)) for ln in a.lanes if not ln.region]
        if a.track is not None and found:
            out[a.track] = found
    return out


@_goldens.needs(THREE)
class NewTrackLanesTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.out = Path(tmp.name)
        self.automated = written(self, "automation", THREE, "--set", "Audio 1:Volume=90@1,40@2",
                                 "--set", "Audio 2:Pan=64@1,0@2", "--set", "Audio 3:Volume=90@1,60@3",
                                 out=self.out / "automated")

    def test_an_added_track_reads_no_lanes(self):
        for flag in ([], ["--instrument"]):
            with self.subTest(flag):
                dest = written(self, "add-track", self.automated, "--name", "Fresh", "--after", "Audio 1",
                               *flag, out=self.out / f"added{len(flag)}")
                self.assertEqual(lanes(dest), lanes(self.automated))

    def test_a_folder_stack_reads_no_lanes_beside_one_that_has_them(self):
        folder = written(self, "stack-create", self.automated, "--name", "D", "--track", "Audio 1",
                         out=self.out / "folder")
        ridden = written(self, "automation", folder, "--set", "D:Volume=90@1,60@3", out=self.out / "ridden")
        dest = written(self, "stack-create", ridden, "--name", "E", "--track", "Audio 2", out=self.out / "second")
        self.assertNotIn("E", lanes(dest))
        self.assertEqual(lanes(dest)["D"], [("Volume", 2)])

    def test_a_summing_header_reads_no_lanes(self):
        folder = written(self, "stack-create", self.automated, "--name", "D", "--track", "Audio 1",
                         out=self.out / "folder")
        ridden = written(self, "automation", folder, "--set", "D:Volume=90@1,60@3", out=self.out / "ridden")
        dest = written(self, "stack-create", ridden, "--name", "S", "--summing", "--track", "Audio 3",
                       out=self.out / "summing")
        self.assertNotIn("S", lanes(dest))
        self.assertEqual(lanes(dest), lanes(ridden))


if __name__ == "__main__":
    unittest.main()
