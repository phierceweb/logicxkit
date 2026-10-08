"""`chains --verify`: Logic's Controls views read back against the tables' decode of the written
bundle. The screen part is a driver run injected here; the refusals, the expected values and the
comparison are tested without Logic."""

import json
import unittest
from pathlib import Path

import _goldens
import _paths  # noqa: F401
from logicxkit.logic.orchestrators.chains_verify import (
    compare_slot,
    expected_rows,
    verify,
    verify_problem,
)
from logicxkit.logicx import project_data

INSERTS = "inserts-native-logic"          # Audio 1: Channel EQ -> Compressor
RENAMED = "addtrack-order-logic"          # the track headed "Audio 1" is bound to channel Audio 3


class RefusalTest(unittest.TestCase):
    def test_not_on_this_platform(self):
        self.assertIn("linux", verify_problem(platform="linux"))

    def test_no_logic_and_no_driver(self):
        self.assertIn("not installed", verify_problem(platform="darwin", app=Path("/nonexistent/Logic.app")))
        self.assertIn("tools/driver", verify_problem(platform="darwin", app=Path("/"), driver=Path("/nonexistent")))

    def test_every_tool_the_driver_runs_is_checked(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            for name in ("controls.py", "axdump.swift"):
                (d / name).write_text("")
            problem = verify_problem(platform="darwin", app=Path("/"), driver=d, which=lambda _n: "/usr/bin/x")
            self.assertIn("axact.swift", problem)
            (d / "axact.swift").write_text("")
            self.assertIn("click.swift", verify_problem(platform="darwin", app=Path("/"), driver=d, which=lambda _n: "/usr/bin/x"))
            (d / "click.swift").write_text("")
            self.assertIsNone(verify_problem(platform="darwin", app=Path("/"), driver=d, which=lambda _n: "/usr/bin/x"))

    def test_no_osascript(self):
        here = Path(__file__).resolve().parents[2] / "tools" / "driver"
        self.assertIn("PATH", verify_problem(platform="darwin", app=Path("/"), driver=here, which=lambda _n: None))


class SlotPairingTest(unittest.TestCase):
    def test_a_slot_pairs_by_logics_short_name_then_by_the_plug_ins_name(self):
        from logicxkit.logic.orchestrators.chains_verify import _take_slot
        slots = [{"short": "Tape Delay"}, {"short": "Tremolo"}]
        self.assertEqual(_take_slot(slots, "Tremolo", "Tremolo"), {"short": "Tremolo"})
        self.assertEqual(_take_slot([{"short": "AdLimit"}], "AdLimit", "Adaptive Limiter"), {"short": "AdLimit"})
        self.assertEqual(_take_slot([{"short": "Multipr"}], "Multipr", "Multipressor"), {"short": "Multipr"})
        self.assertEqual(_take_slot([{"short": "Channel EQ"}], "", "Channel EQ"), {"short": "Channel EQ"})

    def test_a_first_letter_in_common_pairs_nothing(self):
        from logicxkit.logic.orchestrators.chains_verify import _take_slot
        self.assertIsNone(_take_slot([{"short": "Tape Delay"}], "Tremolo", "Tremolo"))
        self.assertIsNone(_take_slot([{"short": "Clarity Vx"}], "Compressor", "Compressor"))
        self.assertIsNone(_take_slot([{"short": "Gate"}], "Gain", "Gain"))


class CompareTest(unittest.TestCase):
    def test_numbers_match_to_the_displays_precision_and_choices_by_name(self):
        expected = {"Gain": 2.0, "Freq": 1000.0, "Mode": "Peak", "Bypass": "Off"}
        shown = [{"label": "Gain", "display": "+2.0 dB"}, {"label": "Freq", "display": "1000 Hz"},
                 {"label": "Mode", "display": "Peak"}, {"label": "Bypass", "display": "0"}]
        self.assertEqual(compare_slot(expected, shown), ([], 4, []))

    def test_a_differing_row_is_named_with_both_values(self):
        expected = {"Gain": 2.0, "Freq": 1000.0}
        shown = [{"label": "Gain", "display": "+3.0 dB"}, {"label": "Freq", "display": "1000 Hz"}]
        differ, agreed, unread = compare_slot(expected, shown)
        self.assertEqual((agreed, unread), (1, []))
        self.assertEqual(differ, ["Gain: file 2.0, Logic shows '+3.0 dB'"])

    def test_a_label_the_view_repeats_pairs_with_the_bands_in_order(self):
        """The Multipressor's view lists four rows labelled Response, band 4 first; the table
        names them Band 4 … Band 1 in the same order."""
        expected = {"Band 4 Response": 100.0, "Band 3 Response": 100.0, "Band 2 Response": 100.0, "Band 1 Response": 200.0,
                    "Band 1 Comp. Ratio": 2.5}
        shown = [{"label": "Response", "display": "100 ms"}, {"label": "Response", "display": "100 ms"},
                 {"label": "Response", "display": "100 ms"}, {"label": "Response", "display": "200 ms"},
                 {"label": "Comp. Ratio", "display": "2.5"}]
        self.assertEqual(compare_slot(expected, shown), ([], 5, []))

    def test_a_display_in_khz_or_with_fewer_decimals_still_agrees(self):
        units = {"Freq": "Hz", "Gain": "dB", "Rel": "ms"}
        shown = [{"label": "Freq", "display": "1.2 kHz"}, {"label": "Gain", "display": "12 dB"}, {"label": "Rel", "display": "0.25 s"}]
        self.assertEqual(compare_slot({"Freq": 1200.0, "Gain": 12.4, "Rel": 250.0}, shown, units), ([], 3, []))
        differ, _agreed, _unread = compare_slot({"Gain": 13.0}, [{"label": "Gain", "display": "12 dB"}], units)
        self.assertEqual(len(differ), 1)

    def test_a_loose_label_match_must_be_the_one_row_that_fits(self):
        shown = [{"label": "Filter Env Attack", "display": "5"}, {"label": "Amp Env Attack", "display": "7"}]
        self.assertEqual(compare_slot({"Attack": 5.0}, shown), ([], 0, ["Attack"]))

    def test_a_parameter_the_view_does_not_show_is_listed_not_judged(self):
        differ, agreed, unread = compare_slot({"Gain": 2.0, "Hidden": 1.0}, [{"label": "Gain", "display": "2.0 dB"}])
        self.assertEqual((differ, agreed, unread), ([], 1, ["Hidden"]))


@_goldens.needs(INSERTS)
class ExpectedRowsTest(unittest.TestCase):
    def test_every_native_slot_of_the_channel_decodes_through_its_table(self):
        rows = expected_rows(project_data(_goldens.path(INSERTS)), ["Audio 1"])
        self.assertEqual(list(rows), ["Audio 1"])
        names = [name for name, _short, _values in rows["Audio 1"]]
        self.assertEqual(names, ["Channel EQ", "Compressor"])
        self.assertEqual([short for _name, short, _values in rows["Audio 1"]], ["Channel EQ", "Compressor"])
        self.assertIn("Threshold", {name: values for name, _short, values in rows["Audio 1"]}["Compressor"])


@_goldens.needs(INSERTS)
class VerifyTest(unittest.TestCase):
    def test_the_driver_is_run_once_and_its_rows_are_compared(self):
        calls = []

        def run(argv):
            calls.append(argv)
            rows = expected_rows(project_data(_goldens.path(INSERTS)), ["Audio 1"])["Audio 1"]
            shown = [{"short": short, "rows": [{"label": k, "display": str(v)} for k, v in values.items()]}
                     for _name, short, values in rows]
            return 0, json.dumps({"tracks": [{"track": "Audio 1", "strip": "Audio 1", "slots": shown}], "problems": []})

        verdict = verify(_goldens.path(INSERTS), ["Audio 1"], run=run)
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0][1].endswith("controls.py"))
        self.assertTrue(verdict.matched, verdict.lines)
        self.assertEqual([ln.split(":")[0] for ln in verdict.lines], ["Audio 1 / Channel EQ", "Audio 1 / Compressor"])

    def test_nothing_compared_is_no_match(self):
        """Rows the view never showed, or a slot of the wrong name, cannot pass the oracle."""
        def run(_argv):
            rows = expected_rows(project_data(_goldens.path(INSERTS)), ["Audio 1"])["Audio 1"]
            return 0, json.dumps({"tracks": [{"track": "Audio 1", "strip": "Audio 1",
                                              "slots": [{"short": "X", "rows": [{"label": "Unrelated", "display": "1"}]} for _ in rows]}],
                                  "problems": []})
        verdict = verify(_goldens.path(INSERTS), ["Audio 1"], run=run)
        self.assertFalse(verdict.matched)
        self.assertTrue(all("no slot of that name" in ln or "not in the file" in ln for ln in verdict.lines), verdict.lines)

        def run2(_argv):
            rows = expected_rows(project_data(_goldens.path(INSERTS)), ["Audio 1"])["Audio 1"]
            return 0, json.dumps({"tracks": [{"track": "Audio 1", "strip": "Audio 1",
                                              "slots": [{"short": short, "rows": [{"label": "Unrelated", "display": "1"}]} for _n, short, _v in rows]}],
                                  "problems": []})
        verdict = verify(_goldens.path(INSERTS), ["Audio 1"], run=run2)
        self.assertFalse(verdict.matched)
        self.assertTrue(all("nothing compared" in ln for ln in verdict.lines), verdict.lines)

    def test_a_logic_slot_the_file_does_not_pair_is_a_difference(self):
        """Logic showed a slot on a track whose file side decodes none: the verdict names it and
        every requested track gets a line."""
        def run(_argv):
            rows = expected_rows(project_data(_goldens.path(INSERTS)), ["Audio 1"])["Audio 1"]
            shown = [{"short": short, "rows": [{"label": k, "display": str(v)} for k, v in values.items()]} for _n, short, values in rows]
            return 0, json.dumps({"tracks": [{"track": "Audio 1", "strip": "Audio 1", "slots": shown},
                                             {"track": "Stereo Out", "strip": "Stereo Out",
                                              "slots": [{"short": "AdLimit", "rows": [{"label": "Gain", "display": "12 dB"}]}]}],
                                  "problems": []})
        verdict = verify(_goldens.path(INSERTS), ["Audio 1", "Stereo Out"], run=run)
        self.assertFalse(verdict.matched)
        self.assertTrue(any(ln.startswith("Stereo Out / AdLimit") and "not in the file" in ln for ln in verdict.lines), verdict.lines)

    def test_a_requested_track_with_no_native_slot_in_the_file_gets_a_line(self):
        def run(_argv):
            return 0, json.dumps({"tracks": [{"track": "Audio 2", "strip": "Audio 2", "slots": []}], "problems": []})
        verdict = verify(_goldens.path(INSERTS), ["Audio 2"], run=run)
        self.assertEqual(verdict.lines, ["Audio 2: no native slot in the file, none on Logic's strip"])
        self.assertIsNone(verdict.problem)

    def test_the_driver_opens_a_copy_of_the_bundle_which_is_then_gone(self):
        """Logic autosaves into the bundle it opens; the original is never the one opened."""
        calls = []

        def run(argv):
            calls.append(argv)
            self.assertTrue(Path(argv[2]).is_dir())
            return 0, json.dumps({"tracks": [{"track": "Audio 1", "strip": "Audio 1", "slots": []}], "problems": []})
        bundle = _goldens.path(INSERTS)
        verify(bundle, ["Audio 1"], run=run)
        opened = Path(calls[0][2])
        self.assertNotEqual(opened.resolve(), bundle.resolve())
        self.assertEqual(opened.name, bundle.name)
        self.assertFalse(opened.exists())

    def test_a_moved_value_is_a_difference(self):
        def run(_argv):
            rows = expected_rows(project_data(_goldens.path(INSERTS)), ["Audio 1"])["Audio 1"]
            shown = []
            for name, short, values in rows:
                shown_rows = [{"label": k, "display": str(v)} for k, v in values.items()]
                if name == "Compressor":
                    shown_rows[0]["display"] = "-99 dB"
                shown.append({"short": short, "rows": shown_rows})
            return 0, json.dumps({"tracks": [{"track": "Audio 1", "strip": "Audio 1", "slots": shown}], "problems": []})

        verdict = verify(_goldens.path(INSERTS), ["Audio 1"], run=run)
        self.assertFalse(verdict.matched)
        self.assertTrue(any("Compressor" in ln and "Logic shows '-99 dB'" in ln for ln in verdict.lines), verdict.lines)

    def test_the_stereo_out_header_reads_the_output_channel(self):
        """Logic's track header says Stereo Out; the file labels that channel Output 1-2."""
        calls = []

        def run(argv):
            calls.append(argv)
            return 0, json.dumps({"tracks": [{"track": "Stereo Out", "strip": "Stereo Out", "slots": []}], "problems": []})

        verdict = verify(_goldens.path(INSERTS), ["Stereo Out"], run=run)
        self.assertEqual(calls[0][-1], "Stereo Out")
        self.assertEqual(verdict.lines, ["Stereo Out: no native slot in the file, none on Logic's strip"])

    def test_a_driver_problem_is_the_verdict(self):
        verdict = verify(_goldens.path(INSERTS), ["Audio 1"], run=lambda _a: (1, "Logic did not open"))
        self.assertFalse(verdict.matched)
        self.assertIn("Logic did not open", verdict.problem)


@_goldens.needs(INSERTS, RENAMED)
class TrackResolutionTest(unittest.TestCase):
    def test_a_channel_label_a_header_name_and_stereo_out_resolve(self):
        from logicxkit.logic.orchestrators.chains_verify import channel_label
        data = project_data(_goldens.path(INSERTS))
        self.assertEqual(channel_label(data, "Audio 1"), "Audio 1")
        self.assertEqual(channel_label(data, "Stereo Out"), "Output 1-2")
        self.assertEqual(channel_label(data, "Audio 10"), "Audio 10")      # not a channel here: left as given

    def test_a_header_bound_to_another_channel_resolves_to_that_channel(self):
        """Logic's `addtrack-order-logic`: the track headed "Audio 1" is bound to channel Audio 3."""
        from logicxkit.logic.orchestrators.chains_verify import channel_label, default_tracks
        data = project_data(_goldens.path(RENAMED))
        self.assertEqual(channel_label(data, "Audio 1"), "Audio 3")
        self.assertEqual(default_tracks(data, {"Audio 3"}), ["Audio 1"])    # the header name the driver matches

    def test_the_default_track_list_is_header_names(self):
        from logicxkit.logic.orchestrators.chains_verify import default_tracks
        data = project_data(_goldens.path(INSERTS))
        self.assertEqual(default_tracks(data, {"Audio 1"}), ["Audio 1"])


if __name__ == "__main__":
    unittest.main()
