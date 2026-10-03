"""`logic automation`'s parsers and the order its write flags apply in, without a project."""

import unittest

from logicxkit.logic._automation_cmd import LANES, _Edit, _lane, _param_lane, _param_points, _points, register
from logicxkit.logic._edit import CommandError
from logicxkit.logic.services.song.events import BAR_ONE
from logicxkit.logic.services.arrange.groups import FADER_IDS
from logicxkit.logic.services.song.signature import Meter, TimeSignature


class LaneTest(unittest.TestCase):
    def test_every_alias_of_the_relative_lane_and_the_plain_lanes(self):
        volume = FADER_IDS["Volume"]
        for text in ("±Volume", "volume±", "Relative Volume", "volume (relative)"):
            self.assertEqual(_lane(text), (volume, True), text)
        self.assertEqual((_lane("Volume"), _lane(" pan ")), ((volume, False), (FADER_IDS["Pan"], False)))
        self.assertEqual(len(LANES), len(FADER_IDS) + 4)

    def test_an_unknown_lane_is_refused_by_name(self):
        with self.assertRaises(CommandError) as e:
            _lane("Width")
        self.assertIn("no lane 'Width'", str(e.exception))


class PointsTest(unittest.TestCase):
    def setUp(self):
        self.bars = Meter([TimeSignature(BAR_ONE, 4, 4)])

    def test_value_at_bar_reads_as_tick_and_value(self):
        self.assertEqual(_points("90@1, 60@5", self.bars), [(BAR_ONE, 90), (BAR_ONE + 4 * 3840, 60)])

    def test_a_parameter_lane_is_slot_and_name_with_values_in_its_own_unit(self):
        self.assertEqual(_param_lane(" slot 3  Band 1 Comp. Threshold "), (3, "Band 1 Comp. Threshold"))
        self.assertEqual(_param_lane("Slot 12 Threshold"), (12, "Threshold"))
        self.assertIsNone(_param_lane("Volume"))
        self.assertIsNone(_param_lane("slot Threshold"))
        points = _param_points("-24.5@1, on@5 ,0@9", self.bars)
        self.assertEqual([v for _t, v in points], [-24.5, True, 0.0])
        self.assertEqual(points[0][0], self.bars.tick(1.0))
        for bad in ("-24", "x@1"):
            with self.assertRaises(CommandError):
                _param_points(bad, self.bars)

    def test_a_point_without_a_bar_or_with_a_bad_number_is_refused(self):
        for text in ("90", "90@", "abc@1", "90@x", "1@90@2"):
            with self.subTest(text), self.assertRaises(CommandError):
                _points(text, self.bars)


class OrderTest(unittest.TestCase):
    def test_the_write_flags_are_kept_in_the_order_typed(self):
        import argparse
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers()
        register(sub)
        args = parser.parse_args(["automation", "p", "--clear", "A:Volume", "--set", "A:Volume=100@1", "--copy", "A:Pan->B"])
        self.assertEqual(args.edits, [("clear", "A:Volume"), ("set", "A:Volume=100@1"), ("copy", "A:Pan->B")])
        self.assertIs(type(parser.parse_args(["automation", "p"]).__dict__.get("edits")), type(None))
        self.assertTrue(issubclass(_Edit, argparse.Action))


if __name__ == "__main__":
    unittest.main()
