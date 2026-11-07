"""Audio effects after an instrument channel's MIDI effects: the shown-slot count Logic keeps counts the
audio effects plus one, the instrument slot aside, and a MIDI effect added under two takes the key
under the reference, moving it up. `add-plugin` writes what Logic's own insert left."""

import struct
import unittest

import _goldens

from logicxkit.logic.services.mixer.add_plugin import add_plugin
from logicxkit.logic.services.mixer.binding import channels
from logicxkit.logic.services.mixer.mixer import CHANNEL_TAG
from logicxkit.logic.services.mixer.plugin_library import find_donor, load_library
from logicxkit.logic.services.mixer.slots import SHOWN_AT, property_key_base
from logicxkit.logic.services.stream.stream import HEADER, project_records
from logicxkit.logicx import project_data
from logicxkit.utils.data import PACKAGED

BASE, ONE, THREE = "instrument-fx-two-midi-logic", "instrument-fx-two-midi-one-audio-logic", "instrument-fx-three-midi-logic"
TWO, TWO_RESAVE = "instrument-fx-two-midi-two-audio-fixed-ours", "instrument-fx-two-midi-two-audio-fixed-resave-logic"


def shown(data: bytes) -> set[int]:
    return {struct.unpack_from("<H", r.raw, HEADER + SHOWN_AT)[0] for r in project_records(data)
            if r.tag == CHANNEL_TAG and len(r.raw) - HEADER >= SHOWN_AT + 2}


def keys(data: bytes, label: str) -> list[tuple[int, int]]:
    owner = next(o for o, c in channels(data).items() if c.label == label)
    return sorted((r.key, len(r.raw) - HEADER) for r in project_records(data) if r.tag == b"UCuA" and r.owner == owner)


@_goldens.needs(BASE, ONE, THREE, TWO, TWO_RESAVE)
class InstrumentShownTest(unittest.TestCase):
    def test_logics_insert_and_third_midi_effect_are_the_facts(self):
        one, three = project_data(_goldens.path(ONE)), project_data(_goldens.path(THREE))
        self.assertEqual((shown(one), [k for k, _n in keys(one, "Inst 1")], property_key_base(one)), ({2}, [2, 3, 4, 5, 9], 6))
        self.assertEqual((shown(three), [k for k, _n in keys(three, "Inst 1")], property_key_base(three)), ({2}, [2, 4, 5, 6, 10], 7))

    def test_add_plugin_keys_and_counts_as_logics_insert_did(self):
        base, one = project_data(_goldens.path(BASE)), project_data(_goldens.path(ONE))
        donor = find_donor(load_library([PACKAGED / "donors"]), "Channel EQ", width=None, version=None)
        owner = next(o for o, c in channels(base).items() if c.label == "Inst 1")
        ours, _report = add_plugin(base, owner, donor.raw, id_offsets=())
        self.assertEqual(shown(ours), shown(one))
        self.assertEqual([k for k, _n in keys(ours, "Inst 1")], [k for k, _n in keys(one, "Inst 1")])
        self.assertEqual(property_key_base(ours), property_key_base(one))

    def test_a_second_audio_effect_comes_back_from_logic_as_written(self):
        two, resaved = project_data(_goldens.path(TWO)), project_data(_goldens.path(TWO_RESAVE))
        self.assertEqual((shown(two), keys(two, "Inst 1"), property_key_base(two)), ({3}, [(2, 656), (3, 432), (4, 236), (5, 780), (6, 308), (10, 406)], 7))
        self.assertEqual((shown(resaved), keys(resaved, "Inst 1"), property_key_base(resaved)), (shown(two), keys(two, "Inst 1"), property_key_base(two)))
        donor = find_donor(load_library([PACKAGED / "donors"]), "Chorus", width=None, version=None)
        one = project_data(_goldens.path(ONE))
        owner = next(o for o, c in channels(one).items() if c.label == "Inst 1")
        ours, _report = add_plugin(one, owner, donor.raw, id_offsets=())
        self.assertEqual((shown(ours), keys(ours, "Inst 1")), (shown(two), keys(two, "Inst 1")))


if __name__ == "__main__":
    unittest.main()
