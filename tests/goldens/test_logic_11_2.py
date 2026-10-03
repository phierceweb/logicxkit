"""A project saved by Logic 11.2 (file header word 2511): class-12 objects typed 1760 over
class-6 channel records, each channel's own uuid in its last 16 bytes and its routing in index
words, held to Logic 12.4's conversion of the same save.

Skips without the owner's files."""

import struct
import unittest

import _goldens
from logicxkit.logic.services.mixer.binding import (
    bound_objects, channels, input_labels, input_routing, output_labels, output_routing)
from logicxkit.logicx import project_data
from logicxkit.logic.services.arrange.environment import channel_objects
from logicxkit.logic.services.arrange.stacks import read_tracks

KEYS = ("logic-11-2-a", "logic-11-2-b")
CONVERTED = {"logic-11-2-a": "logic-11-2-a-converted", "logic-11-2-b": "logic-11-2-b-converted"}


@_goldens.needs(*KEYS)
class Logic112Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.saves = {key: _goldens.path(key).read_bytes() for key in KEYS}

    def test_the_file_is_the_format_this_pins(self):
        for key, data in self.saves.items():
            with self.subTest(key):
                self.assertEqual(struct.unpack_from("<H", data, 4)[0],
                                 _goldens.fact(key, "header_word"))

    def test_every_channel_object_is_read(self):
        for key, data in self.saves.items():
            with self.subTest(key):
                self.assertEqual(len(channel_objects(data)), _goldens.fact(key, "objects"))

    def test_every_in_use_channel_binds_to_exactly_one_object(self):
        for key, data in self.saves.items():
            with self.subTest(key):
                in_use = sorted(o for o, c in channels(data).items() if c.in_use)
                bound = bound_objects(data)
                self.assertEqual(len(in_use), _goldens.fact(key, "in_use"))
                self.assertEqual(sorted(bound), in_use)
                self.assertEqual(len(set(bound.values())), len(bound))

    def test_the_arrange_rows_are_named_and_bound(self):
        for key, data in self.saves.items():
            with self.subTest(key):
                rows = read_tracks(data, _goldens.fact(key, "tracks"))
                self.assertEqual(sum(1 for r in rows if r["name"]),
                                 _goldens.fact(key, "named_rows"))
                self.assertEqual(sum(1 for r in rows if r["owner"] is not None),
                                 _goldens.fact(key, "named_rows"))

    def test_no_channel_carries_a_routing_uuid(self):
        for key, data in self.saves.items():
            with self.subTest(key):
                self.assertEqual((output_routing(data), input_routing(data)), ({}, {}))


@_goldens.needs(*KEYS, *CONVERTED.values())
class RoutingByWordTest(unittest.TestCase):
    """The index words of the Logic 11.2 save name what Logic 12.4 bound by uuid when it
    converted that save."""

    def test_every_in_use_channel_routes_as_logic_12_converted_it(self):
        for key, converted in CONVERTED.items():
            with self.subTest(key):
                old = _goldens.path(key).read_bytes()
                new = project_data(_goldens.path(converted))
                in_use = [o for o, c in channels(old).items() if c.in_use]
                for labels in (output_labels, input_labels):
                    ours, logics = labels(old), labels(new)
                    self.assertEqual({o: ours[o] for o in in_use}, {o: logics[o] for o in in_use})
                routed = sum(1 for o in in_use if output_labels(old)[o] or input_labels(old)[o])
                self.assertGreater(routed, 50)


if __name__ == "__main__":
    unittest.main()
