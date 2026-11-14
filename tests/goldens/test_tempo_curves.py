"""`tempo --set` on maps with 0xb4 and 0xb1 lines. Where the constant-tempo model fits the later points' stored time
words — a curve Logic re-saved, a Tempo List point added to a map with a 0xb1 line — they move with the bar-1 change as
on a bare map; a drawn curve the model sits far off keeps them. A set to the tempo the map already has writes the same
bytes on every one."""

import struct
import unittest

import _goldens

from logicxkit.logic.services.song.events import DATA_LINE, events
from logicxkit.logic.services.song.tempo import BPM_AT, EVENT_TYPE, SCALE, TIME_AT, tempo_sequence
from logicxkit.logic.services.song.tempo_write import MODEL_SLACK, _origin, _points, set_tempo, time_word
from logicxkit.logic.services.stream.stream import HEADER, project_records
from logicxkit.logicx import project_data

FITS = ("mix-03", "tempo-add-bar-103-logic")       # a 0xb4 curve the model fits; a Tempo List point added to a 0xb1 map
OFF = ("mix-04",)                                   # a drawn 0xb4 curve, far off the model


def load(key: str) -> bytes:
    return project_data(_goldens.path(key))


def tempos(d: bytes):
    records = project_records(d)
    return [e for e in events(records[tempo_sequence(records)].raw[HEADER:]) if e.type == EVENT_TYPE]


def words(evs, at: int) -> list[int]:
    return [struct.unpack_from("<I", e.data, at)[0] for e in evs]


def off_the_model(evs) -> int:
    """How far the later events' stored time words sit from the model at worst."""
    first = min(evs, key=lambda e: e.tick)
    return max(abs(struct.unpack_from("<I", e.data, TIME_AT)[0] - time_word(_points(evs), *_origin(evs), e.tick))
               for e in evs if e is not first)


@_goldens.needs(*FITS, *OFF)
class CurvedMapsTest(unittest.TestCase):
    def test_the_maps_carry_lines_past_the_data_line(self):
        for key in FITS + OFF:
            self.assertTrue(any(ln[7] != DATA_LINE for e in tempos(load(key)) for ln in e.lines), key)

    def test_the_model_fits_two_maps_and_not_the_drawn_curve(self):
        for key in FITS:
            self.assertLessEqual(off_the_model(tempos(load(key))), MODEL_SLACK, key)
        for key in OFF:
            self.assertGreater(off_the_model(tempos(load(key))), 1000, key)

    def test_a_set_to_the_same_tempo_writes_the_same_bytes(self):
        for key in FITS + OFF:
            d = load(key)
            bpm = struct.unpack_from("<I", min(tempos(d), key=lambda e: e.tick).data, BPM_AT)[0] / SCALE
            self.assertEqual(set_tempo(d, bpm), d, key)

    def test_a_fitting_maps_later_words_move_to_the_new_model(self):
        for key in FITS:
            d = load(key)
            was, now = tempos(d), tempos(set_tempo(d, 97.0))
            first = min(was, key=lambda e: e.tick)
            after = [(t, 97.0 if t == first.tick else b) for t, b in _points(was)]
            self.assertNotEqual(words(now, TIME_AT)[1:], words(was, TIME_AT)[1:], key)
            for e in now:
                if e.tick != first.tick:
                    self.assertLessEqual(abs(struct.unpack_from("<I", e.data, TIME_AT)[0] - time_word(after, *_origin(was), e.tick)),
                                         MODEL_SLACK, (key, e.tick))
            self.assertEqual(words(now, BPM_AT)[1:], words(was, BPM_AT)[1:], key)
            self.assertEqual(words(now, BPM_AT)[0], round(97.0 * SCALE), key)

    def test_a_drawn_curve_changes_the_bar_1_tempo_and_no_later_word(self):
        for key in OFF:
            d = load(key)
            was, now = tempos(d), tempos(set_tempo(d, 97.0))
            self.assertEqual(words(now, TIME_AT), words(was, TIME_AT), key)
            self.assertEqual(words(now, BPM_AT)[1:], words(was, BPM_AT)[1:], key)
            self.assertEqual(words(now, BPM_AT)[0], round(97.0 * SCALE), key)


if __name__ == "__main__":
    unittest.main()
