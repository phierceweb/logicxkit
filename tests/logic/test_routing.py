"""Output and input routing: the two UUIDs at the tail of a channel record."""

import unittest
from _records import chan, proj, uuid
from logicxkit.logic.services.binding import input_routing, output_routing
from logicxkit.logic.services.routing import set_input, set_output


def session():
    return proj(chan(88, "Inst 5", uuid=uuid(88), dest=uuid(415)),
                chan(401, "Output 1-2", uuid=uuid(80), size=201),
                chan(415, "Output 29-30", uuid=uuid(415), size=201),
                chan(35, "Input 1", uuid=uuid(1), size=201),
                chan(37, "Input 3", uuid=uuid(3), size=201))


class RoutingTest(unittest.TestCase):
    def test_output_moves_to_the_named_channel(self):
        data = session()
        self.assertEqual(output_routing(data)[88], 415)
        out = set_output(data, 88, 401)
        self.assertEqual(output_routing(out)[88], 401)
        self.assertEqual(len(out), len(data))

    def test_input_is_set_the_same_way(self):
        out = set_input(session(), 88, 37)
        self.assertEqual(input_routing(out)[88], 37)

    def test_refuses_a_non_input_as_input(self):
        with self.assertRaises(ValueError):
            set_input(session(), 88, 401)


class NoInputTest(unittest.TestCase):
    def test_none_zeroes_the_input_field(self):
        from _records import chan, proj, uuid
        from logicxkit.logic.services.binding import channels, input_routing
        from logicxkit.logic.services.routing import set_input
        data = proj(chan(0, "Audio 1", uuid=uuid(88), source=uuid(500)), chan(256, "Input 1", uuid=uuid(500), size=201))
        self.assertEqual(input_routing(data)[0], 256)
        out = set_input(data, 0, None)
        self.assertIsNone(input_routing(out)[0])
        self.assertEqual(channels(out)[0].input_uuid, bytes(16))

    def test_no_input_on_an_aux_writes_logics_no_input_bytes(self):
        from _records import chan, proj, uuid
        from logicxkit.logic.services.insert import project_records
        from logicxkit.logic.services.routing import set_input
        data = proj(chan(67, "Aux 1", uuid=uuid(88), source=uuid(500)), chan(500, "Bus 1", uuid=uuid(500), size=201))
        out = set_input(data, 67, None)
        rec_ = next(r for r in project_records(out) if r.owner == 67 and r.tag == b"OCuA")
        self.assertEqual(rec_.raw[36 + 94:36 + 96], b"\xff\xff")
