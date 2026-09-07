"""Which Environment object a mixer channel is bound to, and where it routes.

Both sit at the END of the `OCuA` payload because its length varies per session (257, 265,
269 bytes at one class version): `[len-48:len-32]` is the bound object's UUID, `[len-32:len-16]`
the destination channel's own UUID. `+110` is the Sub number of the channel's stack.
Measured 59/59 on seven sessions and the Recording template, 2026-09-01."""

import unittest
from _records import chan, env_obj, proj, uuid
from logicxkit.logic.services.binding import (
    bound_channels,
    bound_objects,
    channels,
    output_routing,
    set_stack_index,
    stack_channels,
)


def _session():
    return proj(
        env_obj(192, "Drums", grouping=True, uuid=uuid(192)),
        env_obj(88, "Kick In", uuid=uuid(88)),
        env_obj(80, "Master", grouping=True, uuid=uuid(80)),
        chan(378, "Sub 1", uuid=uuid(192)),
        chan(0, "Audio 1", uuid=uuid(88), dest=uuid(1001), stack_index=1),
        chan(121, "Bus 1", uuid=uuid(1001), dest=uuid(80), size=201),
        chan(401, "Output 1-2", uuid=uuid(80), size=201),
        chan(26, "Audio 27", in_use=False),
    )


class ChannelsTest(unittest.TestCase):
    def test_label_in_use_and_stack_index(self):
        c = channels(_session())
        self.assertEqual(c[0].label, "Audio 1")
        self.assertTrue(c[0].in_use)
        self.assertEqual(c[0].stack_index, 1)
        self.assertFalse(c[26].in_use)

    def test_tail_fields_are_length_relative(self):
        c = channels(_session())
        self.assertEqual(c[121].uuid, uuid(1001))       # a 201-byte record
        self.assertEqual(c[0].uuid, uuid(88))            # a 257-byte record


class LinkTest(unittest.TestCase):
    def test_owner_to_object_and_back(self):
        self.assertEqual(bound_objects(_session())[0], 88)
        self.assertEqual(bound_channels(_session())[192], 378)

    def test_unbound_stub_is_absent(self):
        self.assertNotIn(26, bound_objects(_session()))


class RoutingTest(unittest.TestCase):
    def test_destination_resolves_to_the_bus_owner(self):
        self.assertEqual(output_routing(_session())[0], 121)

    def test_a_zero_destination_is_none(self):
        self.assertIsNone(output_routing(_session())[401])


class StackChannelTest(unittest.TestCase):
    def test_sub_number_maps_to_owner(self):
        self.assertEqual(stack_channels(_session()), {1: 378})

    def test_set_stack_index_touches_one_byte(self):
        raw = chan(0, "Audio 1")
        out = set_stack_index(raw, 3)
        diffs = [i for i, (a, b) in enumerate(zip(raw, out, strict=True)) if a != b]
        self.assertEqual(diffs, [36 + 110])
        self.assertEqual(out[36 + 110], 3)
