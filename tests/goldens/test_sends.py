"""Send records: `UCuA` keys 0-2 under a channel's owner, 76 bytes.

`+4` is the send slot (0, 0x10000, 0x20000) and `+20` the destination as bus number plus
the project's mono input count less one (31 in a 32-input project: the drum channels' 46/47
are the B 15 / B 16 the mixer shows; 19 in a 20-input one). The level is NOT decoded —
`+17` varies per send and is a candidate only, so it stays out until a controlled save.

The real-file part of tests/logic/test_sends.py; skips without the owner's files."""

import unittest
import _goldens
from logicxkit.logic.services.sends import bus_owner, read_sends

SAVE = _goldens.path("legacy-pass2-resave")


@_goldens.needs("tracking-template")
class GoldenSendsTest(unittest.TestCase):
    def test_every_send_targets_a_bus_channel_that_exists(self):
        from logicxkit.logicx import project_data
        data = project_data(_goldens.path("tracking-template"))
        sends = read_sends(data)
        self.assertGreater(len(sends), 0)
        for owner, lst in sends.items():
            for s in lst:
                self.assertIsNotNone(bus_owner(data, s.bus), f"owner {owner} -> bus {s.bus}")


@unittest.skipIf(SAVE is None, "Logic's re-save of the 20-input song is not present")
class GoldenSendBaseTest(unittest.TestCase):
    def test_logic_wrote_the_vocal_sends_from_nineteen(self):
        """Logic's own re-save of a 20-input song: the sends it rewrote read as buses 10-12."""
        from logicxkit.logicx import project_data
        from logicxkit.logic.services.sends import send_base
        data = project_data(SAVE)
        self.assertEqual(send_base(data), 19)
        buses = sorted({s.bus for lst in read_sends(data).values() for s in lst})
        self.assertTrue({10, 11, 12} <= set(buses), buses)
        self.assertTrue(all(0 < b <= 64 for b in buses), buses)


if __name__ == "__main__":
    unittest.main()
