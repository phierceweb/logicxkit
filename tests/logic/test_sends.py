"""Send records: `UCuA` keys 0-2 under a channel's owner, 76 bytes.

`+4` is the send slot (0, 0x10000, 0x20000) and `+20` the destination as bus number plus
the project's mono input count less one (31 in a 32-input project: the drum channels' 46/47
are the B 15 / B 16 the mixer shows; 19 in a 20-input one). The level is NOT decoded —
`+17` varies per send and is a candidate only, so it stays out until a controlled save."""

import unittest
from _records import chan, proj, send, uuid
from logicxkit.logic.services.sends import bus_owner, read_sends


class ReadSendsTest(unittest.TestCase):
    def test_slot_and_bus(self):
        data = proj(chan(2, "Audio 3", uuid=uuid(96)), send(2, 0, 15), send(2, 1, 16))
        got = read_sends(data)[2]
        self.assertEqual([(s.slot, s.bus) for s in got], [(0, 15), (1, 16)])

    def test_raw_record_is_kept_for_cloning(self):
        data = proj(send(2, 0, 15))
        self.assertEqual(len(read_sends(data)[2][0].raw), 36 + 76)

    def test_a_channel_without_sends_is_absent(self):
        self.assertEqual(read_sends(proj(chan(0, "Audio 1"))), {})

    def test_a_plugin_slot_under_a_send_key_is_not_a_send(self):
        """Old projects start their plugin slots at key 2: class 424, thousands of bytes."""
        import struct

        from _records import rec
        slot = bytearray(6892)
        struct.pack_into("<I", slot, 0, 424)
        struct.pack_into("<I", slot, 4, 1)
        data = proj(chan(0, "Audio 1"), rec(b"UCuA", 0, 2, bytes(slot), 5), send(0, 0, 15))
        self.assertEqual([(s.key, s.bus) for s in read_sends(data)[0]], [(0, 15)])


class BusOwnerTest(unittest.TestCase):
    def test_bus_label_resolves_to_its_owner(self):
        data = proj(chan(135, "Bus 15", uuid=uuid(5), size=201))
        self.assertEqual(bus_owner(data, 15), 135)
        self.assertIsNone(bus_owner(data, 16))


class SendBaseTest(unittest.TestCase):
    def test_a_project_with_twenty_inputs_counts_from_nineteen(self):
        import struct
        from logicxkit.logic.services.sends import send_base
        inputs = [chan(256 + k, f"Input {k + 1}", size=201, in_use=False) for k in range(20)]
        pairs = [chan(300 + k, f"Input {2 * k + 1}-{2 * k + 2}", size=201, in_use=False) for k in range(10)]
        raw = bytearray(send(2, 0, 10))
        struct.pack_into("<I", raw, 36 + 20, 10 + 19)                  # as Logic writes it there
        data = proj(chan(2, "Audio 3", uuid=uuid(96)), bytes(raw), *inputs, *pairs)
        self.assertEqual(send_base(data), 19)
        self.assertEqual([s.bus for s in read_sends(data)[2]], [10])

    def test_without_input_channels_the_base_is_the_thirty_two_input_one(self):
        from logicxkit.logic.services.sends import send_base
        self.assertEqual(send_base(proj(chan(0, "Audio 1"))), 31)
