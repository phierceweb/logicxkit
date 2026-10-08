"""Drum Machine Designer chosen in an instrument slot's menu (`instrument-drum-machine-designer-logic`):
Logic writes no plug-in slot for it. It builds its Empty Kit track stack — the stack's main, an
aux, carries a kit record; two auxes get the kit's send effects — and the track's channel is
left with no instrument and two sends."""

import struct
import unittest

import _goldens
from logicxkit.logic._edit import owner_by_label
from logicxkit.logic.services.mixer.plugins import project_plugins
from logicxkit.logic.services.mixer.slot_identity import slot_header
from logicxkit.logic.services.mixer.transplant import channel_slots
from logicxkit.logic.services.stream.stream import HEADER, project_records
from logicxkit.logicx import project_data

KEY = "instrument-drum-machine-designer-logic"


@_goldens.needs(KEY)
class DrumMachineDesignerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = project_data(_goldens.path(KEY))

    def test_no_slot_in_the_project_names_it(self):
        names = [slot_header(r.raw[HEADER:]).name for r in project_records(self.data)
                 if r.tag == b"UCuA" and slot_header(r.raw[HEADER:]) is not None]
        self.assertEqual(sorted(names), ["ChromaVerb", "Klopfgeist", "St-Delay"])
        self.assertEqual(sorted(p.name for p in project_plugins(self.data)), ["ChromaVerb", "Klopfgeist", "Stereo Delay"])

    def test_the_track_is_left_with_no_instrument_and_two_sends(self):
        owner = owner_by_label(self.data, "Inst 1")
        self.assertEqual([r.key for r in channel_slots(self.data, owner)], [])
        records = [(r.key, struct.unpack_from("<H", r.raw, HEADER + 4)[0], len(r.raw) - HEADER)
                   for r in project_records(self.data) if r.tag == b"UCuA" and r.owner == owner]
        self.assertEqual(records, [tuple(x) for x in _goldens.fact(KEY, "inst_1_records")])
        self.assertEqual(records[:2], [(0, 0, 76), (1, 0, 76)])

    def test_the_stacks_main_carries_the_kit_record(self):
        kit = _goldens.fact(KEY, "kit")
        owner = owner_by_label(self.data, kit["channel"])
        record = next(r for r in project_records(self.data) if r.tag == b"UCuA" and r.owner == owner and r.key == kit["key"])
        payload = record.raw[HEADER:]
        self.assertEqual((struct.unpack_from("<H", payload, 4)[0], len(payload)), (5, 192))
        self.assertEqual(payload[16:48].split(b"\0")[0].decode(), kit["name"])
        self.assertEqual(payload[80:128].split(b"\0")[0].decode(), kit["category"])
        self.assertEqual((kit["name"], kit["category"]), ("Empty Kit", "Electronic Drums"))

    def test_the_kits_send_effects_sit_on_the_next_auxes_at_the_grown_slot_base(self):
        slots = _goldens.fact(KEY, "slots")
        self.assertEqual(slots, {"Aux 2 key 3": "ChromaVerb", "Aux 3 key 3": "St-Delay", "Inst 2 key 3": "Klopfgeist"})
        control = project_data(_goldens.path("instrument-control-logic"))
        inst2 = owner_by_label(control, "Inst 2")
        self.assertEqual([r.key for r in channel_slots(control, inst2)], [2])


if __name__ == "__main__":
    unittest.main()
