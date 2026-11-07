"""The packaged send template, and a third send on a project whose slot base is 2."""

import struct
import unittest

from _records import chan, proj, uuid
from logic.test_sends_write import bus, donor_send, run, slot

from logicxkit.logic.services.stream.stream import HEADER, project_records
from logicxkit.logic.services.mixer.sends import read_sends
from logicxkit.logic.services.mixer.sends_write import add_send, remove_sends


class PackagedSendTemplateTest(unittest.TestCase):
    def test_a_project_without_sends_gets_one_from_the_package(self):
        data = proj(chan(0, "Audio 1", uuid=uuid(88)), bus(1))
        out, report = add_send(data, owner=0, bus=1)
        (made,) = read_sends(out)[0]
        self.assertEqual((made.bus, made.level, report["key"]), (1, 0, 0))


def _base_2(data: bytes) -> bytes:
    """Every channel record stamped with slot base 2, as a project made before Logic 11.2."""
    from logicxkit.logic.services.mixer.mixer import CHANNEL_BASE_AT, is_mixer_record
    from logicxkit.logic.services.stream.stream import reassemble
    out = []
    for r in project_records(data):
        raw = bytearray(r.raw)
        if is_mixer_record(r):
            struct.pack_into("<H", raw, HEADER + CHANNEL_BASE_AT, 2)
        out.append(bytes(raw))
    return reassemble(data, out)


class ThirdSendAtBase2Test(unittest.TestCase):
    """At slot base 2 key 2 is the third send's and slot 1's at once, and Logic drops the plug-in
    (`legacy-migrate-fixed-logic`); the third send moves the project to base 4 (`slotkeys`)."""

    def _project(self) -> bytes:
        return _base_2(proj(chan(2, "Audio 3", uuid=uuid(96)), donor_send(2, 0, 15), donor_send(2, 1, 16),
                            slot(2, 2), bus(10), bus(15), bus(16)))

    def test_the_slot_moves_up_past_the_third_send(self):
        from logicxkit.logic.services.mixer.slots import slot_index_base
        out, report = add_send(self._project(), owner=2, bus=10)
        self.assertEqual(report["key"], 2)
        self.assertEqual([k for _t, k in run(out, 2)], [0xFFFF, 0, 1, 2, 4])
        self.assertEqual(slot_index_base(out), 4)

    def test_two_sends_leave_the_base_alone(self):
        from logicxkit.logic.services.mixer.slots import slot_index_base
        data = self._project()
        out = remove_sends(data, owner=2)
        out, _ = add_send(out, owner=2, bus=10)
        self.assertEqual(slot_index_base(out), 2)


if __name__ == "__main__":
    unittest.main()
