"""The write gate's binding check: an in-use channel no object is bound to."""

import unittest

import _goldens
from _records import chan, env_obj, proj, uuid

from logicxkit.logic.services.mixer.binding import channels
from logicxkit.logic.services.stream.stream import HEADER, project_records
from logicxkit.logic.services.stream.integrity import (
    _binding, _lost_bindings, regressions, structural_report)
from logicxkit.logicx import project_data

KEY = "tracks-three-audio-logic"


UNBOUND = "no track object is bound to"


def lost(before: bytes, after: bytes) -> list[str]:
    return _lost_bindings(_binding(before), _binding(after))


class UnboundChannelTest(unittest.TestCase):
    def _session(self, *, lost: int | None = None, shift: int = 0, bound: bool = True) -> bytes:
        """Kick In on Audio 1, Snare on Audio 2 and a free Audio 3; ``lost`` names the channel
        whose uuid matches no object, ``shift`` moves every owner up."""
        ids = {0: 88, 1: 92}
        return proj(env_obj(88, "Kick In"), env_obj(92, "Snare"),
                    *(chan(owner + shift, f"Audio {owner + 1}",
                           uuid=uuid(999 if owner == lost or not bound else ids[owner]))
                      for owner in ids),
                    chan(2 + shift, "Audio 3", in_use=False))

    def test_an_in_use_channel_with_no_object_is_named(self):
        self.assertEqual(_binding(self._session(lost=1))["unbound_channels"], [1])
        self.assertEqual(_binding(self._session())["unbound_channels"], [])

    def test_losing_one_is_a_regression(self):
        self.assertEqual(len(lost(self._session(), self._session(lost=1))), 1)

    def test_losing_every_binding_is_a_regression(self):
        self.assertEqual(len(lost(self._session(), self._session(bound=False))), 1)

    def test_one_the_input_had_is_not_new_after_the_owners_shift(self):
        self.assertEqual(lost(self._session(lost=1), self._session(lost=1, shift=1)), [])

    def test_a_project_that_binds_nothing_by_uuid_is_not_judged(self):
        before = proj(env_obj(88, "Kick In", ver=11), chan(0, "Audio 1", size=233, ver=6))
        after = proj(env_obj(88, "Kick In", ver=11), chan(0, "Audio 1", size=233, ver=6),
                     chan(1, "Audio 2", size=233, ver=6))
        self.assertEqual(lost(before, after), [])


@_goldens.needs(KEY)
class UnboundIsARegressionTest(unittest.TestCase):
    def test_logics_own_save_has_none_and_losing_one_is_refused(self):
        before = project_data(_goldens.path(KEY))
        self.assertEqual(structural_report(before)["unbound_channels"], [])
        owner = min(o for o, c in channels(before).items() if c.in_use)
        after, at = bytearray(before), 24
        for record in project_records(before):
            if record.tag == b"OCuA" and record.owner == owner and len(record.raw) - HEADER > 200:
                after[at + len(record.raw) - 48] ^= 0xFF
            at += len(record.raw)
        found = regressions(before, bytes(after))
        self.assertTrue(any(UNBOUND in line and str(owner) in line for line in found), found)


if __name__ == "__main__":
    unittest.main()
