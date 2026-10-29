"""The drum quantize writer, end to end on a blank-born public project: two audio regions
made from click tracks, one the reference, quantized to a 1/16 grid without Logic."""

import struct
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

import _goldens
from logicxkit.logic.services.regions.audio_regions import read_audio_regions
from logicxkit.logic.services.regions.audio_write import add_audio_region
from logicxkit.logic.services.arrange.environment import object_id_of
from logicxkit.logic.services.song.events import BAR_ONE, PPQ
from logicxkit.logic.services.regions.flexmarkers import END, HIT, START, RBA_CODE_AT, RBA_OBJECT_AT, RBA_ROW_AT
from logicxkit.logic.services.regions.flexmode import flex_mode, q_reference
from logicxkit.logic.services.arrange.groups import group_errors, read_groups
from logicxkit.logic.services.stream.stream import project_records
from logicxkit.logic.services.midi.midi import read_midi
from logicxkit.logic.services.regions.quantize_drums import quantize_drums
from logicxkit.logic.services.regions.regions import region_errors
from logicxkit.logic.services.song.tempo import project_tempo
from logicxkit.logic.services.song.tempo_write import add_ramp, add_tempo
from logicxkit.logic.services.stream.validate import validate_project
from logicxkit.logicx import project_data
from _quantize import (
    KICK, RATE, SNARE, clicks, marker_blocks, rba_headers,
)


@_goldens.needs("midi-write-resave-logic")
class QuantizeTest(unittest.TestCase):
    KICK_BEATS = [0.02, 1.0, 2.05, 3.0, 4.03, 5.0, 6.02, 7.0]      # a little off the grid
    SNARE_BEATS = [1.05, 3.02, 5.06, 7.03]

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        media = Path(self.tmp.name) / "Media" / "Audio Files"
        data = project_data(_goldens.path("midi-write-resave-logic"))
        self.bpm = project_tempo(data)[1]
        data, _ = add_audio_region(data, track=KICK, start=BAR_ONE, wav=clicks(Path(self.tmp.name) / "kick.wav", self.KICK_BEATS, self.bpm), media_folder=media)
        data, _ = add_audio_region(data, track=SNARE, start=BAR_ONE, wav=clicks(Path(self.tmp.name) / "snare.wav", self.SNARE_BEATS, self.bpm), media_folder=media)
        self.base = data
        self.wav_of = lambda region: media / region.file.name
        self.out, self.report = quantize_drums(data, members=[KICK, SNARE], references=[KICK], wav_of=self.wav_of, groups_off=("OH",))

    def tearDown(self):
        self.tmp.cleanup()

    def objects(self, data):
        return {object_id_of(r): r.raw for r in project_records(data) if object_id_of(r) is not None}

    def test_the_project_stays_whole(self):
        self.assertEqual(validate_project(self.out), [])
        self.assertEqual(region_errors(self.out), [])
        self.assertEqual(group_errors(self.out), [])
        self.assertEqual([r.track for r in read_audio_regions(self.out)], [KICK, SNARE])
        self.assertEqual(read_midi(self.out), read_midi(self.base))     # the base's MIDI region is untouched

    def test_the_group_and_the_objects(self):
        (g,) = [g for g in read_groups(self.out) if g.name == "Drums"]
        ids = {r.object_id for r in read_audio_regions(self.out)}
        self.assertEqual(set(g.members), ids)
        self.assertTrue(g.on)
        self.assertLessEqual({"Editing (Selection)", "Quantize-Locked (Audio)", "Volume", "Mute", "Automation Mode"}, set(g.settings))
        self.assertEqual((self.report.group, self.report.group_created, self.report.groups_off), (g.number, True, []))
        by_id = self.objects(self.out)
        regions = {r.track: r.object_id for r in read_audio_regions(self.out)}
        self.assertTrue(q_reference(by_id[regions[KICK]]))
        self.assertFalse(q_reference(by_id[regions[SNARE]]))
        self.assertEqual([flex_mode(by_id[regions[t]]) for t in (KICK, SNARE)], ["Slicing", "Slicing"])

    def test_every_member_region_carries_the_hits_on_the_grid(self):
        spb = RATE * 60 / self.bpm
        blocks = marker_blocks(self.out)
        regions = {r.track: r for r in read_audio_regions(self.out)}
        for track in (KICK, SNARE):
            b = blocks[regions[track].object_id]
            self.assertEqual([x[6] for x in b], [START] + [HIT] * len(self.KICK_BEATS) + [END], track)
            self.assertEqual(struct.unpack_from("<i", b[0], 0)[0], -round(spb))
            self.assertEqual(struct.unpack_from("<i", b[0], 12)[0], -PPQ)
            for beat, hit in zip(self.KICK_BEATS, b[1:-1], strict=True):
                source, target = struct.unpack_from("<i", hit, 0)[0], struct.unpack_from("<i", hit, 12)[0]
                self.assertLessEqual(abs(source - beat * spb), RATE // 1000, (track, beat))
                self.assertEqual(target, round(beat * 4) * PPQ // 4)
            self.assertEqual(struct.unpack_from("<i", b[-1], 0)[0], regions[track].frames)
        self.assertEqual(self.report.hits, len(self.KICK_BEATS))

    def test_each_region_gets_an_rba_sequence_with_the_value(self):
        heads = rba_headers(self.out)
        regions = {r.object_id: r for r in read_audio_regions(self.out)}
        self.assertEqual(len(heads), 2)
        for p in heads:
            self.assertEqual(struct.unpack_from("<h", p, RBA_CODE_AT)[0], -6)
            oid = struct.unpack_from("<I", p, RBA_OBJECT_AT)[0]
            self.assertIn(oid, regions)
            self.assertEqual(struct.unpack_from("<h", p, RBA_ROW_AT)[0], -regions[oid].row)
        self.assertEqual(rba_headers(self.base), [])

    def test_a_second_pass_reuses_the_group_and_replaces_the_markers(self):
        again, report = quantize_drums(self.out, members=[KICK, SNARE], references=[KICK, SNARE], wav_of=self.wav_of, grid=8)
        self.assertEqual((report.group, report.group_created), (self.report.group, False))
        self.assertEqual(len([g for g in read_groups(again) if g.name == "Drums"]), 1)
        self.assertEqual(len(rba_headers(again)), 2)
        self.assertEqual({struct.unpack_from("<h", p, RBA_CODE_AT)[0] for p in rba_headers(again)}, {-8})
        blocks = marker_blocks(again)
        n = len(self.KICK_BEATS)               # every snare hit sits within 50 ms of a kick hit: one hit each
        self.assertEqual([len(b) for b in blocks.values() if b], [n + 2, n + 2])
        self.assertTrue(all(struct.unpack_from("<i", x, 12)[0] % (PPQ // 2) == 0 for b in blocks.values() for x in b if x[6] == HIT))
        self.assertEqual(validate_project(again), [])

    def test_refusals(self):
        with self.assertRaises(ValueError):
            quantize_drums(self.base, members=[KICK], references=[SNARE], wav_of=self.wav_of)
        with self.assertRaises(ValueError):
            quantize_drums(self.base, members=[KICK, SNARE], references=[KICK], wav_of=lambda r: None)
        with self.assertRaises(ValueError):
            quantize_drums(self.base, members=[KICK, SNARE], references=[KICK], wav_of=self.wav_of, grid=12)

    def test_reference_audio_without_hits_is_refused(self):
        silent = clicks(Path(self.tmp.name) / "silent.wav", [], self.bpm)
        with self.assertRaisesRegex(ValueError, r"no hits .*silent\.wav"):
            quantize_drums(self.base, members=[KICK, SNARE], references=[KICK], wav_of=lambda region: silent)

    def test_a_tempo_change_or_ramp_is_refused(self):
        bar = 4 * PPQ
        changed = {"step": add_tempo(self.base, BAR_ONE + 2 * bar, self.bpm + 20),
                   "ramp": add_ramp(self.base, BAR_ONE + bar, self.bpm, BAR_ONE + 2 * bar, self.bpm + 20)}
        for name, data in changed.items():
            with self.subTest(name), self.assertRaisesRegex(ValueError, "changes tempo"):
                quantize_drums(data, members=[KICK, SNARE], references=[KICK], wav_of=self.wav_of)

    def test_an_extra_point_at_the_same_tempo_quantizes_alike(self):
        same = add_tempo(self.base, BAR_ONE + 8 * PPQ, self.bpm)
        out, _ = quantize_drums(same, members=[KICK, SNARE], references=[KICK], wav_of=self.wav_of, groups_off=("OH",))
        self.assertEqual(list(marker_blocks(out).values()), list(marker_blocks(self.out).values()))

    def test_a_region_without_its_arrange_entry_is_a_value_error(self):
        moved = [replace(r, start=r.start + 1) for r in read_audio_regions(self.base)]
        with mock.patch("logicxkit.logic.services.regions.quantize_drums.read_audio_regions", return_value=moved), \
                self.assertRaisesRegex(ValueError, "entry"):
            quantize_drums(self.base, members=[KICK, SNARE], references=[KICK], wav_of=self.wav_of)

if __name__ == "__main__":
    unittest.main()
