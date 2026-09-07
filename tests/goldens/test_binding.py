"""Which Environment object a mixer channel is bound to, and where it routes.

Both sit at the END of the `OCuA` payload because its length varies per session (257, 265,
269 bytes at one class version): `[len-48:len-32]` is the bound object's UUID, `[len-32:len-16]`
the destination channel's own UUID. `+110` is the Sub number of the channel's stack.
Measured 59/59 on seven sessions and the tracking template, 2026-09-01.

The real-file part of tests/logic/test_binding.py; skips without the owner's files."""

import unittest
import _goldens
from logicxkit.logic.services.binding import (
    bound_objects,
    channels,
    output_routing,
    stack_channels,
)



TEMPLATE = _goldens.path("tracking-template")


@_goldens.needs("tracking-template")
class GoldenBindingTest(unittest.TestCase):
    """Pins the decode to a Logic-written file, not to bytes a test wrote itself."""

    @classmethod
    def setUpClass(cls):
        from logicxkit.logicx import project_data
        cls.data = project_data(TEMPLATE)

    def test_every_in_use_channel_binds_to_exactly_one_object(self):
        c = channels(self.data)
        in_use = [o for o, ch in c.items() if ch.in_use]
        bound = bound_objects(self.data)
        self.assertEqual(sorted(in_use), sorted(bound))
        self.assertEqual(len(set(bound.values())), len(bound))

    def test_folder_stacks_bind_to_sub_strips(self):
        from logicxkit.logic.services.environment import channel_objects
        names = {i: o.name for i, o in channel_objects(self.data).items()}
        subs = stack_channels(self.data)
        objs = bound_objects(self.data)
        self.assertEqual(names[objs[subs[1]]], "Drums")
        self.assertEqual(names[objs[subs[2]]], "Bass")

    def test_the_kick_channel_shares_its_bus_with_most_of_the_kit(self):
        """Drums feed three buses (close mics, cymbals, rooms); the close mics are the majority."""
        c = channels(self.data)
        routing = output_routing(self.data)
        kick = next(o for o, ch in c.items() if ch.label == "Audio 1")
        dest = routing[kick]
        self.assertTrue(c[dest].label.startswith("Bus "))
        kit = [o for o, ch in c.items() if ch.stack_index == 1 and ch.label.startswith("Audio")]
        self.assertGreaterEqual(sum(1 for o in kit if routing[o] == dest), 10)


if __name__ == "__main__":
    unittest.main()
