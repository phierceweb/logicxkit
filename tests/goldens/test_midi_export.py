"""`logic midi --export` held to Logic's own saves: the tempo list's points and the signature
list's meter change on the conductor track, and a refusal for events before bar 1."""

import contextlib
import io
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _goldens
from logicxkit.cli import main
from logicxkit.logic.services.song.events import BAR_ONE
from logicxkit.logic.services.midi.midi import read_midi
from logicxkit.logic.services.midi.midi_write import add_note, add_region
from logicxkit.logic.services.midi.smf import meter_map, tempo_map, write_smf
from logicxkit.logic.services.song.tempo import project_tempo
from logicxkit.logicx import project_data

TEMPO, METER, EMPTY = "tempo-point-140-logic", "signature-meter-created-logic", "midi-empty-region-logic"


def conductor(smf: bytes) -> list[tuple[int, int, bytes]]:
    """(absolute tick, meta type, data) of every event on track 0."""
    size = struct.unpack_from(">I", smf, 18)[0]
    track, pos, at, out = smf[22:22 + size], 0, 0, []
    while pos < len(track):
        delta = 0
        while True:
            b = track[pos]
            pos += 1
            delta = delta << 7 | b & 0x7F
            if not b & 0x80:
                break
        at += delta
        kind, n = track[pos + 1], track[pos + 2]
        out.append((at, kind, track[pos + 3:pos + 3 + n]))
        pos += 3 + n
    return out


def tempos(smf: bytes) -> list[tuple[int, int]]:
    return [(t, int.from_bytes(d, "big")) for t, k, d in conductor(smf) if k == 0x51]


def run(*argv) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        rc = main(["logic", "midi", *map(str, argv)])
    return rc, buf.getvalue()


class _Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()


@_goldens.needs(TEMPO)
class TempoMapTest(_Tmp):
    def test_every_tempo_point_is_a_tempo_event_at_its_tick_from_bar_1(self):
        points = [tuple(p) for p in _goldens.fact(TEMPO, "tempos")]
        data = project_data(_goldens.path(TEMPO))
        self.assertEqual(tempo_map(data), points)
        want = [(tick - BAR_ONE, round(60_000_000 / bpm)) for tick, bpm in points]
        self.assertEqual(tempos(write_smf(read_midi(data), tempos=tempo_map(data), meters=meter_map(data))), want)

    def test_without_a_tempo_track_the_bar_1_tempo_not_the_lcds(self):
        data = project_data(_goldens.path(TEMPO))
        lcd, bar_one = project_tempo(data)
        self.assertNotEqual(lcd, bar_one)
        with mock.patch("logicxkit.logic.services.midi.smf.read_tempo_events", return_value=[]):
            self.assertEqual(tempo_map(data), [(BAR_ONE, bar_one)])

    def test_the_cli_writes_the_tempo_map(self):
        mid = self.out / "song.mid"
        rc, text = run(_goldens.path(TEMPO), "--export", mid)
        self.assertEqual(rc, 0, text)
        self.assertEqual(tempos(mid.read_bytes()),
                         [(tick - BAR_ONE, round(60_000_000 / bpm)) for tick, bpm in _goldens.fact(TEMPO, "tempos")])


@_goldens.needs(METER)
class MeterMapTest(unittest.TestCase):
    def test_a_meter_change_lands_on_its_bar(self):
        data = project_data(_goldens.path(METER))
        smf = write_smf([], tempos=tempo_map(data), meters=meter_map(data))
        got = [(t, d[0], 1 << d[1]) for t, k, d in conductor(smf) if k == 0x58]
        facts = zip(_goldens.fact(METER, "meter_ticks"), _goldens.fact(METER, "meters"), strict=True)
        self.assertEqual(got, [(max(tick - BAR_ONE, 0), n, d) for tick, (n, d) in facts])


@_goldens.needs(EMPTY)
class BeforeBarOneTest(_Tmp):
    def test_write_smf_refuses_an_event_before_bar_1(self):
        data, _ = add_region(project_data(_goldens.path(EMPTY)), track="Inst 1", start=BAR_ONE - 3840, length=3840, name="pickup")
        data = add_note(data, track="Inst 1", tick=BAR_ONE - 960, pitch=60, velocity=100, length=240)
        with self.assertRaisesRegex(ValueError, "'pickup' on 'Inst 1'.*before bar 1"):
            write_smf(read_midi(data), tempos=tempo_map(data), meters=meter_map(data))

    def test_the_cli_prints_the_refusal_and_exits_1(self):
        rc, text = run(_goldens.path(EMPTY), "--out", self.out / "copy", "--region", "Inst 1:0:1:pickup",
                       "--note", "Inst 1:0.75:60:100:240")
        self.assertEqual(rc, 0, text)
        (project,) = (self.out / "copy").rglob("*.logicx")
        mid = self.out / "pickup.mid"
        rc, text = run(project, "--export", mid)
        self.assertEqual(rc, 1, text)
        self.assertIn("before bar 1", text)
        self.assertFalse(mid.exists())

    def test_with_json_the_refusal_keeps_stdout_clean(self):
        rc, text = run(_goldens.path(EMPTY), "--out", self.out / "copy", "--region", "Inst 1:0:1:pickup",
                       "--note", "Inst 1:0.75:60:100:240")
        self.assertEqual(rc, 0, text)
        (project,) = (self.out / "copy").rglob("*.logicx")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = main(["logic", "midi", str(project), "--json", "--export", str(self.out / "pickup.mid")])
        self.assertEqual((rc, out.getvalue()), (1, ""))
        self.assertIn("before bar 1", err.getvalue())


@_goldens.needs("regions-a10-midi-split-logic")
class SplitExportTest(unittest.TestCase):
    def test_each_piece_exports_only_the_notes_it_plays(self):
        from groovebin.midi import read
        data = project_data(_goldens.path("regions-a10-midi-split-logic"))
        regions = read_midi(data)
        self.assertEqual([len(r.events) for r in regions], [2, 2])
        self.assertEqual([[e.tick for e in r.played] for r in regions], [[], [51840]])
        song = read(write_smf(regions, tempos=tempo_map(data), meters=meter_map(data)))
        self.assertEqual([len(part.notes) for part in song.tracks[1:]], [0, 1])


if __name__ == "__main__":
    unittest.main()
