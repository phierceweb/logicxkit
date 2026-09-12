"""Slot key bases: when a project is rebased from Logic's old slot layout and when it is not."""

import unittest

import _paths  # noqa: F401


class RebaseOnlyOnCollisionTest(unittest.TestCase):
    """A project born in Logic 12.3.1 sits at slot base 2 and Logic keeps it there on re-save
    (a blank project, 2026-09-12); the 2020 song Logic moved to base 4 carried a channel with
    three sends, so key 2 was a send and a slot at once. Rebase only on that collision."""

    @staticmethod
    def base2(with_third_send: bool) -> bytes:
        from _records import chan, proj, rec, send
        slot = bytearray(400)
        slot[6] = 0                                  # a key-2 slot, index 0
        slot[40:46] = b"<plist"
        parts = [chan(0, "Audio 1"), rec(b"UCuA", 0, 2, bytes(slot), 5), send(0, 0, 5), send(0, 1, 6)]
        if with_third_send:
            parts.append(send(0, 2, 7))
        return proj(*parts)

    def test_a_base_two_project_without_a_key_two_send_is_left_alone(self):
        from logicxkit.logic.services.slotkeys import needs_rebase
        self.assertFalse(needs_rebase(self.base2(False)))

    def test_a_key_two_send_beside_key_two_slots_needs_the_rebase(self):
        from logicxkit.logic.services.slotkeys import needs_rebase
        self.assertTrue(needs_rebase(self.base2(True)))
