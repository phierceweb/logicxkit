"""The `logic midi` transform flags: the parser (steps grouped, presets, `--quantize` routed by shape,
`--select` merged), the seed, the target rules, and the service's refusals — without a real file."""

import argparse
import unittest

import _paths  # noqa: F401
from groovebin.transforms import Operation, Range
from logicxkit.logic._edit import CommandError
from logicxkit.logic._midi_transform_cmd import parse, seed_of, targets
from logicxkit.logic._midi_cmd import register
from logicxkit.logic.services.midi.midi_transform import Transform


def args(*argv):
    ap = argparse.ArgumentParser()
    register(ap.add_subparsers())
    return ap.parse_args(["midi", "song.logicx", *argv])


class ParseTest(unittest.TestCase):
    def test_flags_land_in_order_and_consecutive_ops_form_one_pass(self):
        a = args("1", "2", "--select", "pitch=36-47", "--select", "velocity<40", "--add", "velocity=10", "--set", "length=1/8",
                 "--humanize", "--min", "velocity=20", "--quantize", "position=1/16", "--quantize", "1=1/16", "--reverse", "pitch")
        self.assertEqual((a.regions, a.edits), ([1, 2], [("quantize", "1=1/16")]))
        t = parse(a.steps, a.select)
        self.assertEqual(t.select, {"pitch": Range(36, 47), "velocity": Range(None, 40, hi_open=True)})
        self.assertEqual(t.steps, (("ops", [Operation("velocity", "add", 10), Operation("length", "set", 480)]),
                                   ("preset", ("humanize", (10, 8, 5))),
                                   ("ops", [Operation("velocity", "min", 20), Operation("tick", "quantize", 240), Operation("pitch", "reverse")])))

    def test_each_preset_shape(self):
        a = args("--fixed-velocity", "90", "--velocity-limit", "--velocity-limit", "30..100", "--random-velocity", "--reverse-position",
                 "--reverse-pitch", "--reverse-pitch", "60", "--exp-velocity", "1.6", "--fixed-length", "1/8", "--max-length", "480",
                 "--min-length", "120t", "--half-speed", "--double-speed", "--legato", "--staccato", "40%", "--swing", "60%:1/8",
                 "--crescendo", "40..120", "--crescendo", "velocity=1..127", "--humanize", "pos=1/32,len=0")
        names = [(p[0], p[1]) if k == "preset" else ("ops", p) for k, p in parse(a.steps, None).steps]
        self.assertEqual(names, [("fixed-velocity", 90), ("velocity-limit", (20, 110)), ("velocity-limit", (30, 100)),
                                 ("random-velocity", 20), ("reverse-position", None), ("reverse-pitch", None), ("reverse-pitch", 60),
                                 ("exp-velocity", 1.6), ("fixed-length", 480), ("max-length", 480), ("min-length", 120),
                                 ("half-speed", None), ("double-speed", None), ("legato", 100.0), ("staccato", 40.0),
                                 ("swing", (0.6, 8)), ("crescendo", (40, 120)), ("ops", [Operation("velocity", "crescendo", (1, 127))]),
                                 ("humanize", (120, 8, 0))])

    def test_no_transform_flags_is_none_and_a_bare_select_is_refused(self):
        self.assertIsNone(parse(None, None))
        with self.assertRaisesRegex(CommandError, "--select needs an operation or a preset"):
            parse(None, ["pitch=36"])

    def test_bad_specs_name_the_flag(self):
        for argv, message in [(["--select", "size=3", "--legato"], r"bad --select 'size=3': no note field"),
                              (["--select", "pitch=36", "--select", "pitch=40", "--legato"], "pitch is given twice"),
                              (["--set", "velocity", "--legato"], r"bad --set 'velocity': set takes FIELD=VALUE"),
                              (["--fixed-velocity", "loud"], r"bad --fixed-velocity 'loud': 'loud' is not a whole number"),
                              (["--select", "pitch=36", "--half-speed"], "takes the whole region; drop --select"),
                              (["--select", "pitch=36", "--swing", "60%"], "takes the whole region; drop --select"),
                              (["--swing", "60%:1/12"], "not a grid"), (["--exp", "length=2"], None)]:
            a = args(*argv)
            with self.subTest(argv):
                if message is None:
                    parse(a.steps, a.select)      # exp on another field is refused when applied, not parsed
                    continue
                with self.assertRaisesRegex(CommandError, message):
                    parse(a.steps, a.select)

    def test_seed(self):
        self.assertEqual(seed_of("7"), 7)
        self.assertLess(seed_of("random"), 2**32)
        with self.assertRaisesRegex(CommandError, "bad --seed '-1'"):
            seed_of("-1")

    def test_an_optional_value_preset_that_ate_the_region_number_says_so(self):
        for flag in ("--random-velocity", "--reverse-pitch", "--exp-velocity", "--legato", "--staccato"):
            a = args(flag, "3")
            with self.subTest(flag), self.assertRaisesRegex(CommandError, rf"\{flag} took '3' as its own value"):
                targets(b"", None, a.regions, a.track, a.steps)
        a = args("--fixed-velocity", "90")            # a required value is no one's region number
        with self.assertRaisesRegex(CommandError, "name the regions to transform by number"):
            targets(b"", None, a.regions, a.track, a.steps)


class TransformTest(unittest.TestCase):
    def test_moves_notes_past_events_is_every_step_that_moves_a_tick(self):
        for steps in ((("ops", [Operation("tick", "reverse")]),), (("ops", [Operation("tick", "quantize", 240)]),),
                      (("ops", [Operation("tick", "mul", 2)]),), (("ops", [Operation("tick", "add", 960)]),),
                      (("ops", [Operation("tick", "random", 3)]),), (("ops", [Operation("tick", "flip", 480)]),),
                      (("preset", ("reverse-position", None)),), (("preset", ("swing", (0.6, 16))),),
                      (("preset", ("humanize", (10, 8, 5))),), (("preset", ("humanize", None)),)):
            with self.subTest(steps):
                self.assertTrue(Transform({}, steps).moves_notes_past_events)
        for steps in ((("preset", ("reverse-pitch", None)), ("ops", [Operation("velocity", "random", 3)])),
                      (("ops", [Operation("length", "quantize", 240)]),), (("preset", ("legato", 100.0)),),
                      (("preset", ("humanize", (0, 8, 5))),)):
            with self.subTest(steps):
                self.assertFalse(Transform({}, steps).moves_notes_past_events)
        self.assertFalse(Transform({}, (("preset", ("half-speed", None)),)).moves_notes_past_events, "stretch moves the events too")


if __name__ == "__main__":
    unittest.main()
