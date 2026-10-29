"""A strip-silence spec: groups of tracks, each with the command's settings under the flags'
names, read into one `Settings` per group with the command's own refusals."""

import json
import tempfile
import unittest
from pathlib import Path

import _paths  # noqa: F401
from _paths import REPO

from logicxkit.logic._silence_spec import read_spec, settings_from

EXAMPLE = REPO / "config" / "example-strip-silence.json"


class SpecTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.n = 0

    def spec(self, groups, top=None) -> Path:
        self.n += 1
        path = self.dir / f"spec{self.n}.json"
        path.write_text(json.dumps({"groups": groups} if top is None else top))
        return path

    def test_each_group_reads_into_its_own_settings(self):
        groups = read_spec(self.spec([
            {"tracks": ["Bass"], "min_gap": 2, "threshold": -24, "edge": -18, "fade": 30},
            {"tracks": ["Vox"], "ref": ["OH"], "band": "300:3000", "min_gap": 1.5, "above": 7, "gate": 3, "window": 200},
            {"tracks": ["Floor"], "ref": ["Snare", "Kick"], "band": "60:400", "tilt_band": "auto", "against_band": "400:2000",
             "tilt": 3, "min_keep": 0.05, "pad": "50:600"},
        ]))
        self.assertEqual([g.tracks for g in groups], [("Bass",), ("Vox",), ("Floor",)])
        bass, vox, floor = (g.settings for g in groups)
        self.assertEqual((bass.min_gap_s, bass.threshold_db, bass.edge_db, bass.fade_ms, bass.pad_ms, bass.refs), (2, -24, -18, 30, (500, 500), ()))
        self.assertEqual((vox.refs, vox.band, vox.min_gap_s, vox.above_db, vox.gate_db, vox.window_ms), (("OH",), (300, 3000), 1.5, 7, 3, 200))
        self.assertIsNone(bass.gate_db)
        self.assertEqual((floor.refs, floor.band, floor.tilt_band, floor.against, floor.tilt_db, floor.min_keep_s, floor.pad_ms),
                         (("Snare", "Kick"), (60, 400), "auto", (400, 2000), 3, 0.05, (50, 600)))

    def test_a_pad_and_a_ref_may_be_one_figure_or_a_list(self):
        (g,) = read_spec(self.spec([{"tracks": ["A"], "ref": "OH", "pad": 250}]))
        self.assertEqual((g.settings.refs, g.settings.pad_ms), (("OH",), (250, 250)))
        (g,) = read_spec(self.spec([{"tracks": ["A"], "pad": [50, 600], "band": None}]))
        self.assertEqual((g.settings.pad_ms, g.settings.band), ((50, 600), None))

    def test_the_example_spec_reads(self):
        groups = read_spec(EXAMPLE)
        self.assertEqual(len(groups), 4)
        self.assertEqual(groups[2].settings.gate_db, 3)
        self.assertEqual(groups[3].settings.tilt_band, "auto")

    def refused(self, groups, what: str, top=None):
        with self.subTest(what), self.assertRaisesRegex(ValueError, what):
            read_spec(self.spec(groups, top))

    def test_the_shape_is_refused_by_name(self):
        self.refused(None, "a spec is", top={"tracks": ["A"]})
        self.refused(None, "a spec is", top=[{"tracks": ["A"]}])
        self.refused([], "a spec is")
        self.refused(None, "'min_gap' at the top level", top={"groups": [{"tracks": ["A"]}], "min_gap": 2})
        self.refused(["A"], "group 1 needs \"tracks\"")
        self.refused([{"min_gap": 2}], "group 1 needs \"tracks\"")
        for tracks in ("A", [], [["A"]], [7]):
            self.refused([{"tracks": tracks}], "group 1 needs \"tracks\"")
        self.refused([{"tracks": ["A"]}, {"tracks": ["A"]}], "'A' is in two groups \\(1 and 2\\)")
        self.refused([{"tracks": ["A", "A"]}], "'A' is named twice in group 1")
        self.refused([{"tracks": ["A"], "gap": 2}], "unknown setting 'gap'")
        self.refused([{"tracks": ["A", "B"], "ref": ["OH", "B"]}], "'B'.*both cut and a reference")
        self.refused([{"tracks": ["A"], "ref": "A"}], "'A'.*both cut and a reference")
        self.refused([{"tracks": ["A"], "ref": [3]}], "ref names tracks")
        self.refused([{"tracks": ["A"], "ref": ["B", "B"]}], "ref 'B' is named twice")
        bad = self.dir / "bad.json"
        bad.write_text("{not json")
        with self.assertRaisesRegex(ValueError, "bad.json: Expecting"):
            read_spec(bad)
        (g,) = read_spec(self.spec([{"tracks": ["A"], "ref": ["B"], "against_band": "400:2000", "tilt_band": " Auto "}]))
        self.assertEqual(g.settings.tilt_band, "auto")

    def test_the_rules_flags_need_their_rule(self):
        for key, value in (("above", 6), ("gate", 3), ("window", 50), ("against_band", "400:2000")):
            self.refused([{"tracks": ["A"], key: value}], f"{key} is the bleed rule's; it needs ref")
        for key, value in (("tilt", 3), ("tilt_band", "60:120")):
            self.refused([{"tracks": ["A"], "ref": ["B"], key: value}], f"{key} needs against_band")

    def test_numbers_are_refused_out_of_range_or_not_numbers(self):
        self.refused([{"tracks": ["A"], "threshold": 6}], "threshold 6: 0 or below")
        self.refused([{"tracks": ["A"], "edge": 1}], "edge 1: 0 or below")
        self.refused([{"tracks": ["A"], "threshold": -20, "edge": -30}], "edge -30 is further under")
        self.assertEqual(settings_from({"threshold": -15}).edge_db, -15)          # the default edge never sits under a given threshold
        self.refused([{"tracks": ["A"], "threshold": "nan"}], "threshold 'nan': a number")
        self.refused([{"tracks": ["A"], "threshold": "loud"}], "threshold 'loud': a number")
        self.refused([{"tracks": ["A"], "min_gap": True}], "min_gap True: a number")
        for key in ("min_gap", "min_keep"):
            self.refused([{"tracks": ["A"], key: -1}], f"{key} -1: 0 or more")
        self.refused([{"tracks": ["A"], "ref": ["B"], "above": 0}], "above 0: above 0")
        self.refused([{"tracks": ["A"], "ref": ["B"], "gate": -1}], "gate -1: 0 or more")
        for key in ("fade", "window"):
            self.refused([{"tracks": ["A"], "ref": ["B"], key: -5}], f"{key} -5: whole ms")
            self.refused([{"tracks": ["A"], "ref": ["B"], key: 0.5}], f"{key} 0.5: whole ms")
        for value in ("50:x", ":600", "50:", "-5", -5, 12.5, "12.5", True, [50], [50, "x"]):
            self.refused([{"tracks": ["A"], "pad": value}], "pad")
        for value in ("300", "3000:300", "0:100", "a:b", "1:2:3", [300], [300.9, 3000.7], "300.5:3000", [True, 3000]):
            self.refused([{"tracks": ["A"], "band": value}], "a band is LOW:HIGH in whole Hz")
        self.refused([{"tracks": ["A"], "min_gap": 1e305}], "min_gap 1e\\+305: 86400 or below")
        self.refused([{"tracks": ["A"], "min_keep": 90000}], "min_keep 90000: 86400 or below")
        self.refused([{"tracks": ["A"], "ref": ["B"], "above": 4000}], "above 4000: 200 or below")
        self.refused([{"tracks": ["A"], "ref": ["B"], "gate": 201}], "gate 201: 200 or below")
        self.refused([{"tracks": ["A"], "ref": ["B"], "against_band": "400:2000", "tilt": -300}], "tilt -300: -200 or more")
        self.refused([{"tracks": ["A"], "threshold": -300}], "threshold -300: -200 or more")
        self.refused([{"tracks": ["A"], "fade": 70000}], "fade 70000: whole ms, 0 to 65535")
        self.refused([{"tracks": ["A"], "ref": ["B"], "window": 4000000}], "window 4000000: whole ms, 0 to 3600000")
        self.refused([{"tracks": ["A"], "pad": 4000000}], "a pad is MS, or BEFORE:AFTER in whole ms, 0 to 3600000")
        self.refused([{"tracks": ["A"], "ref": ["B"], "against_band": "400:2000", "tilt_band": "x"}], "a band is LOW:HIGH")


if __name__ == "__main__":
    unittest.main()
