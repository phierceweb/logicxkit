"""The time word of an added tempo point, from the tempo map alone."""

import struct
import unittest

import _goldens
from _cli import data

from logicxkit.logic.services.song.events import LINE, events
from logicxkit.logic.services.song.tempo import BPM_AT, EVENT_TYPE, SCALE, TIME_AT, tempo_sequence
from logicxkit.logic.services.song.tempo_write import MODEL_SLACK, set_tempo, time_word
from logicxkit.logic.services.stream.stream import HEADER, project_records, reassemble

POINT_12, POINT_13, SET_13 = "tempo-point-140-logic", "tempo-point-140-13-0-logic", "tempo-set-ours-resave-13-0-logic"
RAMP = "tempo-ramp-ours-13-0"                                      # fifteen bare events from bar 9


def tempo_times(d: bytes) -> list[tuple[int, int]]:
    """(tick, time word) of every tempo event."""
    return [(e.tick, struct.unpack_from("<I", e.data, TIME_AT)[0]) for e in tempos(d)]


def tempos(d: bytes):
    records = project_records(d)
    return [e for e in events(records[tempo_sequence(records)].raw[HEADER:]) if e.type == EVENT_TYPE]


def nudged(d: bytes, index: int, by: int) -> bytes:
    """The map with tempo event ``index``'s time word moved by ``by``."""
    records = project_records(d)
    i = tempo_sequence(records)
    raw = bytearray(records[i].raw)
    e = tempos(d)[index]
    at = raw.index(e.head + b"".join(e.lines), HEADER) + LINE * (1 + e.lines.index(e.data)) + TIME_AT
    struct.pack_into("<I", raw, at, struct.unpack_from("<I", raw, at)[0] + by)
    out = [r.raw for r in records]
    out[i] = bytes(raw)
    return reassemble(d, out)


@_goldens.needs(POINT_12, POINT_13, SET_13)
class LaterEventsFollowTheSetTest(unittest.TestCase):
    """A tempo set at bar 1 moves the time every later point falls at; the writer recomputes their time words."""

    def test_the_later_points_time_is_recomputed(self):
        was = tempo_times(data(POINT_12))
        now = tempo_times(set_tempo(data(POINT_12), 110))
        self.assertEqual([t for t, _w in now], [t for t, _w in was])
        self.assertEqual(now[0], was[0])                                           # the origin keeps its time
        self.assertNotEqual(now[1][1], was[1][1])
        self.assertEqual(now[1][1], time_word([(was[0][0], 110.0), (was[1][0], 140.0)], was[0][0], was[0][1], was[1][0]))

    def test_it_is_the_word_logic_13_0_wrote(self):
        self.assertEqual(tempo_times(set_tempo(data(POINT_13), 110)), tempo_times(data(SET_13)))


@_goldens.needs(RAMP)
class EveryLaterPointMovesTest(unittest.TestCase):
    def test_a_set_to_the_same_tempo_writes_the_same_bytes(self):
        d = data(RAMP)
        bpm = struct.unpack_from("<I", tempos(d)[0].data, BPM_AT)[0] / SCALE
        self.assertEqual(set_tempo(d, bpm), d)

    def test_every_later_point_moves_by_the_first_segments_change(self):
        """A bar-1 change alters the first segment alone, so every later word moves by what the model gives for the first
        later point under the new tempo less what it gives under the old, to the rounding of the sums."""
        d = data(RAMP)
        was, now = tempo_times(d), tempo_times(set_tempo(d, 110))
        self.assertEqual(len(was), 15)
        (t0, w0), (t1, _w1) = was[0], was[1]
        bpm = struct.unpack_from("<I", tempos(d)[0].data, BPM_AT)[0] / SCALE
        shift = time_word([(t0, 110.0)], t0, w0, t1) - time_word([(t0, bpm)], t0, w0, t1)
        self.assertGreater(shift, 1000)
        moves = [w - v for (_t, v), (_u, w) in zip(was[1:], now[1:], strict=True)]
        self.assertTrue(all(abs(m - shift) <= 1 for m in moves), (shift, moves))

    def test_a_word_a_unit_off_the_model_keeps_its_offset(self):
        """The move is by the model's change, not to the model: a stored word within the slack keeps its offset."""
        d = data(RAMP)
        plain, bumped = tempo_times(set_tempo(d, 110)), tempo_times(set_tempo(nudged(d, 3, MODEL_SLACK), 110))
        self.assertEqual([w - v for (_t, v), (_u, w) in zip(plain, bumped, strict=True)], [0, 0, 0, MODEL_SLACK] + [0] * 11)

    def test_a_map_the_model_does_not_fit_keeps_every_later_word(self):
        """One later word past the slack (a drawn curve's shape) and the bar-1 change moves no time word."""
        d = nudged(data(RAMP), 3, MODEL_SLACK + 1)
        now = set_tempo(d, 110)
        self.assertEqual(tempo_times(now), tempo_times(d))
        self.assertEqual(struct.unpack_from("<I", tempos(now)[0].data, BPM_AT)[0], round(110 * SCALE))


ORIGIN = (38400, 7_200_000)          # bar 1 at Logic's default SMPTE start, 01:00:00:00


class TimeWordTest(unittest.TestCase):
    def test_constant_tempo(self):
        self.assertEqual(time_word([(38400, 120.0)], *ORIGIN, 55680), 7_218_000)      # 18 beats at 120 = 9 s

    def test_the_origin_itself_and_anything_before_it(self):
        self.assertEqual(time_word([(38400, 120.0)], *ORIGIN, 38400), 7_200_000)
        self.assertEqual(time_word([(38400, 120.0)], *ORIGIN, 0), 7_200_000)

    def test_segments_take_their_own_tempo(self):
        points = [(38400, 120.0), (42240, 60.0)]                 # 4 beats at 120 (2 s), then 60
        self.assertEqual(time_word(points, *ORIGIN, 46080), 7_200_000 + 2000 * (2 + 4))

    def test_rounds_to_the_unit(self):
        self.assertEqual(time_word([(38400, 175.7186)], *ORIGIN, 38400 + 480), 7_200_000 + 341)


if __name__ == "__main__":
    unittest.main()
