"""An instrument channel's Smart Controls as Logic writes them: the first archive's mappings, each
naming the instrument by `kGInstIDKey` and its parameter by index, the second's layout. ES2 as Logic
inserted it (`instrument-es2-logic`, Logic 12.4): 11 mappings at id 104 and the "Automatic-Modern
Synth 8 Single Row" layout with its knob labels; ours leaves the layout "Automatic" with no mappings,
which Logic kept (`instrument-write-es2-logic`). Logic 13.0's re-save of a 12.4 blank gave Klopfgeist
six mappings at id 76 and the same layout name (`tracks-two-audio-13-0-logic`)."""

import plistlib
import struct
import unittest

import _goldens

from logicxkit.logic.services.mixer.binding import channels
from logicxkit.logic.services.mixer.slots import archive_index
from logicxkit.logic.services.mixer.smart_controls import _mappings
from logicxkit.logic.services.stream.stream import HEADER, project_records
from logicxkit.logicx import project_data

ES2, OURS, KLOPFGEIST = "instrument-es2-logic", "instrument-write-es2-logic", "tracks-two-audio-13-0-logic"
SIZE_AT, BPLIST_AT = 16, 20
LAYOUT = "Automatic-Modern Synth 8 Single Row"


def archives(key: str, label: str = "Inst 1") -> dict[int, list]:
    """archive index -> the bplist's `$objects`."""
    data = project_data(_goldens.path(key))
    owner = next(o for o, c in channels(data).items() if c.label == label)
    out = {}
    for r in project_records(data):
        payload = r.raw[HEADER:]
        if r.tag == b"UCuA" and r.owner == owner and (n := archive_index(r.raw)) is not None:
            size = struct.unpack_from("<I", payload, SIZE_AT)[0]
            out[n] = plistlib.loads(payload[BPLIST_AT:BPLIST_AT + size])["$objects"]
    return out


def instrument_ids(objects: list) -> set[int]:
    return {m["kGInstIDKey"] for m in _mappings(objects)}


def strings(objects: list) -> list[str]:
    return [o for o in objects if isinstance(o, str)]


@_goldens.needs(ES2, OURS, KLOPFGEIST)
class SmartControlsInstrumentTest(unittest.TestCase):
    def test_logics_es2_carries_eleven_mappings_and_a_named_layout(self):
        found = archives(ES2)
        self.assertEqual(sorted(found), [1, 2])
        self.assertEqual((len(_mappings(found[1])), instrument_ids(found[1])), (11, {104}))
        self.assertIn(LAYOUT, strings(found[2]))
        self.assertEqual([s for s in strings(found[2]) if s in ("Cutoff", "Resonance", "Attack", "Decay")],
                         ["Cutoff", "Resonance", "Attack", "Decay"])

    def test_ours_stays_automatic_and_logic_kept_it(self):
        found = archives(OURS)
        self.assertEqual(sorted(found), [2])
        self.assertIn("Automatic", strings(found[2]))
        self.assertNotIn(LAYOUT, strings(found[2]))

    def test_logic_13_gives_klopfgeist_six_mappings(self):
        found = archives(KLOPFGEIST)
        self.assertEqual(sorted(found), [1, 2])
        self.assertEqual((len(_mappings(found[1])), instrument_ids(found[1])), (6, {76}))
        self.assertIn(LAYOUT, strings(found[2]))


if __name__ == "__main__":
    unittest.main()
