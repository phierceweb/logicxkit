"""`slots.property_key_base` on a project no channel of which names a strip: the archive pair,
then a lone archive, then the channel words (slot base + shown slots + 1)."""

import struct
import unittest

from _records import proj
from logicxkit.logic.services.mixer.mixer import CHANNEL_TAG
from logicxkit.logic.services.mixer.slots import property_key_base
from logicxkit.logic.services.stream.stream import HEADER, project_records, reassemble
from test_add_plugin_growth import archive
from test_transplant_ids import mono_chan, native

OWNER = 3


def _with_words(data: bytes, words: dict[int, tuple[int, int]]) -> bytes:
    """Each channel record's slot base (`+28`) and shown slots (`+30`), by owner."""
    out = []
    for r in project_records(data):
        raw = bytearray(r.raw)
        if r.tag == CHANNEL_TAG and r.owner in words:
            struct.pack_into("<HH", raw, HEADER + 28, *words[r.owner])
        out.append(bytes(raw))
    return reassemble(data, out)


def _project(*satellites: bytes) -> bytes:
    return proj(mono_chan(OWNER, "Inst 1"), *satellites, mono_chan(5, "Audio 5"))


class PropertyBaseTest(unittest.TestCase):
    def test_a_lone_archive_places_the_base(self):
        for key, n in ((8, 2), (7, 1)):
            with self.subTest(archive=n):
                self.assertEqual(property_key_base(_project(native(OWNER, 4, 1), archive(OWNER, key, n))), 5)

    def test_a_pair_wins_over_a_lone_archive_elsewhere(self):
        data = proj(mono_chan(OWNER, "Inst 1"), archive(OWNER, 11, 1), archive(OWNER, 12, 2),
                    mono_chan(5, "Audio 5"), archive(5, 14, 2))
        self.assertEqual(property_key_base(data), 9)

    def test_no_archive_reads_the_channel_words(self):
        for words, base in (((2, 2), 5), ((3, 4), 8), ((4, 2), 7)):
            with self.subTest(words=words):
                data = _with_words(_project(), {OWNER: words, 5: words})
                self.assertEqual(property_key_base(data), base)

    def test_words_that_are_not_a_layout_fall_back(self):
        self.assertEqual(property_key_base(_project()), 10)                                  # none written
        self.assertEqual(property_key_base(_with_words(_project(), {OWNER: (2, 2), 5: (2, 3)})), 10)
        self.assertEqual(property_key_base(_with_words(_project(), {OWNER: (7, 2), 5: (7, 2)})), 10)

    def test_a_third_midi_effect_on_a_channel_is_refused_as_unmeasured(self):
        """Two MIDI effects are measured (`instrument-fx-two-midi-logic`); where a third's key sits is not."""
        from _records import rec
        def midi(key: int) -> bytes:
            payload = bytearray(192)
            struct.pack_into("<H", payload, 4, 2)
            return rec(b"UCuA", OWNER, key, bytes(payload), 5)
        two = _with_words(_project(midi(6), midi(7)), {OWNER: (2, 2), 5: (2, 2)})
        self.assertEqual(property_key_base(two), 6)
        three = _with_words(_project(midi(6), midi(7), midi(8)), {OWNER: (2, 2), 5: (2, 2)})
        with self.assertRaises(ValueError):
            property_key_base(three)


if __name__ == "__main__":
    unittest.main()
