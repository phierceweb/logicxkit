"""The channel-count record's `+61` copies the shown-slot word every channel record carries at `+30`:
`show_slots` writes it, so a chain written past the shown slots (`transplant`, `chains`, `add-plugin`)
leaves the project as Logic's re-save of one would."""

import struct
import tempfile
import unittest
from pathlib import Path

import _goldens
from _cli import data, run

from logicxkit.logic.services.mixer.mixer import CHANNEL_TAG, is_channel_count
from logicxkit.logic.services.mixer.shown import SHOWN_MIRROR_AT, show_slots
from logicxkit.logic.services.mixer.slots import SHOWN_AT
from logicxkit.logic.services.stream.stream import HEADER, project_records

TWO, INSERTS = "tracks-two-audio-logic", "inserts-native-all-logic"     # shown 2; Audio 1 with eight slots, shown 9


def shown_words(d: bytes) -> set[int]:
    return {struct.unpack_from("<H", r.raw, HEADER + SHOWN_AT)[0] for r in project_records(d)
            if r.tag == CHANNEL_TAG and len(r.raw) - HEADER >= SHOWN_AT + 2}


def count_record(d: bytes) -> bytes:
    (record,) = [r.raw[HEADER:] for r in project_records(d) if is_channel_count(r)]
    return record


@_goldens.needs(TWO, INSERTS)
class ShownMirrorTest(unittest.TestCase):
    def test_raising_the_shown_word_writes_the_count_records_copy_and_nothing_else_there(self):
        before = count_record(data(TWO))
        self.assertEqual((shown_words(data(TWO)), before[SHOWN_MIRROR_AT]), ({2}, 2))
        after = count_record(show_slots(data(TWO), 9))
        self.assertEqual((shown_words(show_slots(data(TWO), 9)), after[SHOWN_MIRROR_AT]), ({9}, 9))
        self.assertEqual(after[:SHOWN_MIRROR_AT] + after[SHOWN_MIRROR_AT + 1:], before[:SHOWN_MIRROR_AT] + before[SHOWN_MIRROR_AT + 1:])

    def test_a_lower_count_leaves_the_words_and_the_copy_equal_to_them(self):
        out = show_slots(data(TWO), 1)
        self.assertEqual((shown_words(out), count_record(out)[SHOWN_MIRROR_AT]), ({2}, 2))

    def test_a_transplanted_chain_leaves_the_copy_at_the_channels_word(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, text = run("transplant", _goldens.path(INSERTS), _goldens.path(TWO), "--channel", "Audio 1=Audio 1", "--out", tmp)
            self.assertEqual(code, 0, text)
            d = data(next(Path(tmp).glob("*.logicx")))
            self.assertEqual((shown_words(d), count_record(d)[SHOWN_MIRROR_AT]), ({9}, 9))


if __name__ == "__main__":
    unittest.main()
