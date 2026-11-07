"""`transplant` (and every `insert_slots` caller) on a chain that grows into the keys Logic keeps
under the reference: the reference, the records under it and the archives above it move up on
every channel, as `add_plugin` already does and as Logic's re-save of a chain written without the
move did (`strip-reference-chains-resave-logic`)."""

import unittest

from _records import proj
from logicxkit.logic.services.mixer.slots import property_key_base
from logicxkit.logic.services.mixer.transplant import transplant
from logicxkit.logic.services.stream.keyflags import flag_errors
from test_add_plugin_growth import OWNER, _keyed, archive, stray
from test_transplant_ids import mono_chan, native, ref

SRC = 7


def _dst(*slots: bytes) -> bytes:
    """Channel 3 with ``slots``, reference at 10, archives at 12 and 13; channel 5 with one slot."""
    return proj(mono_chan(OWNER, "Audio 3"), *slots, stray(OWNER, 9), ref(OWNER, 10),
                archive(OWNER, 12, 1), archive(OWNER, 13, 2),
                mono_chan(5, "Audio 5"), native(5, 4, 50), ref(5, 10), archive(5, 12, 1), archive(5, 13, 2))


def _src(count: int) -> bytes:
    """A source project laid out for ``count`` slots on keys 4.., its own reference above them."""
    top = 4 + count + 2
    return proj(mono_chan(SRC, "Audio 7"), *(native(SRC, 4 + i, i) for i in range(count)),
                ref(SRC, top), archive(SRC, top + 2, 1), archive(SRC, top + 3, 2))


class TransplantGrowthTest(unittest.TestCase):
    def test_a_longer_chain_pushes_the_layout_up_on_every_channel(self):
        dst = _dst(*(native(OWNER, 4 + i, i) for i in range(4)))
        out, _report = transplant(_src(5), dst, src_owner=SRC, dst_owner=5)
        self.assertEqual(_keyed(out, 5), [4, 5, 6, 7, 8, 11, 13, 14])
        self.assertEqual(_keyed(out, OWNER), [4, 5, 6, 7, 10, 11, 13, 14])
        self.assertEqual((property_key_base(out), flag_errors(out)), (11, []))

    def test_a_chain_no_longer_than_the_projects_moves_nothing_under_a_short_headroom(self):
        """Two keys between the chain and the reference, as Logic lays an instrument with one effect out:
        a chain of the same length stays, the headroom floor of three notwithstanding."""
        dst = proj(mono_chan(OWNER, "Audio 3"), *(native(OWNER, 4 + i, i) for i in range(4)), ref(OWNER, 9),
                   archive(OWNER, 11, 1), archive(OWNER, 12, 2),
                   mono_chan(5, "Audio 5"), native(5, 4, 50), ref(5, 9), archive(5, 11, 1), archive(5, 12, 2))
        out, _report = transplant(_src(4), dst, src_owner=SRC, dst_owner=5)
        self.assertEqual(_keyed(out, 5), [4, 5, 6, 7, 9, 11, 12])
        self.assertEqual(_keyed(out, OWNER), [4, 5, 6, 7, 9, 11, 12])

    def test_a_chain_inside_the_range_moves_nothing(self):
        dst = _dst(*(native(OWNER, 4 + i, i) for i in range(4)))
        out, _report = transplant(_src(3), dst, src_owner=SRC, dst_owner=5)
        self.assertEqual(_keyed(out, 5), [4, 5, 6, 10, 12, 13])
        self.assertEqual(_keyed(out, OWNER), [4, 5, 6, 7, 9, 10, 12, 13])


if __name__ == "__main__":
    unittest.main()
