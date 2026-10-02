"""`drums-to-midi` end to end on blank-born public projects with click-track audio: notes at the
clicks on their keys, velocities, the region span, the grid, the threshold, regions that start
inside or cut through their file, overlapping regions, a 3/4 meter, and the refusals."""

import argparse
import contextlib
import io
import shutil
import struct
import tempfile
import unittest
from pathlib import Path

import _goldens
from test_onsets import RATE, riff, slow_track, track, write_wav

from logicxkit.logic._drums_to_midi_cmd import register
from logicxkit.logic.services.audio_regions import REGION_FRAMES_AT, REGION_OFFSET_AT, REGION_TAG, read_audio_regions
from logicxkit.logic.services.audio_write import add_audio_region
from logicxkit.logic.services.drums_to_midi import SIXTEENTH, drums_to_midi
from logicxkit.logic.services.events import BAR_ONE, PPQ
from logicxkit.logic.services.stream import HEADER, project_records, reassemble
from logicxkit.logic.services.integrity import regressions
from logicxkit.logic.services.midi import read_midi
from logicxkit.logic.services.midi_write import track_regions
from logicxkit.logic.services.onsets import Detector
from logicxkit.logic.services.tempo import project_tempo
from logicxkit.logic.services.tempo_write import add_ramp, add_tempo
from logicxkit.logic.services.validate import validate_project
from logicxkit.logicx import project_data

GOLDEN = "midi-write-resave-logic"
KICK, SNARE, TARGET = "Audio 1", "Audio 2", "Untitled"
BAR = 4 * PPQ
KICK_NOTE, SNARE_NOTE = 36, 38                       # Addictive Drums 2's kick and snare
TOLERANCE = 3                                         # ticks: the detector lands within a sample or two


def clicks(path: Path, beats: list[float], amps: list[float], bpm: float, seconds: float = 4.5) -> Path:
    spb = RATE * 60 / bpm
    write_wav(path, track([(int(b * spb), a) for b, a in zip(beats, amps, strict=True)], seconds=seconds))
    return path


def reframed(data: bytes, index: int, *, offset: int, frames: int) -> bytes:
    """The ``index``-th audio region record given another first frame in its file and length."""
    out, k = [], 0
    for r in project_records(data):
        raw = bytearray(r.raw)
        if r.tag == REGION_TAG:
            if k == index:
                struct.pack_into("<I", raw, HEADER + REGION_OFFSET_AT, offset)
                struct.pack_into("<I", raw, HEADER + REGION_FRAMES_AT, frames)
            k += 1
        out.append(bytes(raw))
    return reassemble(data, out)


def command(argv: list[str]) -> tuple[int, str]:
    ap = argparse.ArgumentParser()
    register(ap.add_subparsers())
    args = ap.parse_args(["drums-to-midi", *argv])
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = args.func(args)
    return rc, buf.getvalue()


@_goldens.needs(GOLDEN)
class DrumsToMidiTest(unittest.TestCase):
    KICK_BEATS = [0.02, 1.0, 2.05, 3.0, 4.03, 5.0, 6.02, 7.0]
    KICK_AMPS = [0.3, 0.8, 0.5, 0.6, 0.4, 0.7, 0.35, 0.9]
    SNARE_BEATS = [1.0, 3.02]                         # in the file; its region starts at bar 2
    SNARE_AMPS = [0.4, 0.8]

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.media = self.dir / "Media" / "Audio Files"
        self.golden = project_data(_goldens.path(GOLDEN))
        self.bpm = project_tempo(self.golden)[1]
        self.base = self.session(self.KICK_BEATS, self.KICK_AMPS)
        self.hits = [(KICK, "kick"), (SNARE, "snare")]

    def tearDown(self):
        self.tmp.cleanup()

    def session(self, kick_beats, kick_amps, kick_name="kick.wav"):
        data, _ = add_audio_region(self.golden, track=KICK, start=BAR_ONE, media_folder=self.media,
                                   wav=clicks(self.dir / kick_name, kick_beats, kick_amps, self.bpm))
        data, _ = add_audio_region(data, track=SNARE, start=BAR_ONE + BAR, media_folder=self.media,
                                   wav=clicks(self.dir / "snare.wav", self.SNARE_BEATS, self.SNARE_AMPS, self.bpm))
        return data

    def wav_of(self, region):
        return self.media / region.file.name

    def run_it(self, data=None, **kw):
        return drums_to_midi(data or self.base, hits=kw.pop("hits", self.hits), target=TARGET, wav_of=self.wav_of, **kw)

    def new_region(self, before, after):
        (region,) = [r for r in read_midi(after) if r not in read_midi(before)]
        return region

    def test_notes_land_at_the_clicks_on_their_keys(self):
        out, report = self.run_it()
        region = self.new_region(self.base, out)
        self.assertEqual((region.track, region.start), (TARGET, BAR_ONE))
        want = sorted([(round(b * PPQ), KICK_NOTE) for b in self.KICK_BEATS]
                      + [(BAR + round(b * PPQ), SNARE_NOTE) for b in self.SNARE_BEATS])
        got = sorted((e.tick - BAR_ONE, e.pitch) for e in region.events)
        self.assertEqual([p for _t, p in got], [p for _t, p in want])
        for (t, _p), (w, _q) in zip(got, want, strict=True):
            self.assertLessEqual(abs(t - w), TOLERANCE, (t, w))
        self.assertTrue(all(e.length == SIXTEENTH and e.channel == 1 for e in region.events))
        self.assertEqual([(t, h) for t, _term, _n, h in report.hits], [(KICK, 8), (SNARE, 2)])
        self.assertEqual(validate_project(out), [])
        self.assertEqual(regressions(self.base, out), [])

    def test_the_region_spans_the_whole_bars_holding_the_hits(self):
        out, report = self.run_it()
        region = self.new_region(self.base, out)
        (placed,) = [r for r in track_regions(out, TARGET) if r.start == region.start]
        self.assertEqual(placed.length, 2 * BAR)
        self.assertEqual((report.start_bar, report.bars), (1, 2))
        self.assertIn([r for r in read_midi(self.base)][0], read_midi(out))          # the golden's own region stays

    def test_velocity_follows_the_click_amplitude(self):
        out, _ = self.run_it()
        events = sorted(self.new_region(self.base, out).events, key=lambda e: e.tick)
        kicks = [e.velocity for e in events if e.pitch == KICK_NOTE]
        order = sorted(range(len(kicks)), key=lambda k: self.KICK_AMPS[k])
        self.assertEqual(order, sorted(range(len(kicks)), key=lambda k: kicks[k]))
        self.assertEqual((min(kicks), max(kicks)), (1, 127))
        self.assertEqual([e.velocity for e in events if e.pitch == SNARE_NOTE], [1, 127])

    def test_grid_snaps_the_notes(self):
        out, report = self.run_it(grid=16)
        region = self.new_region(self.base, out)
        ticks = sorted(e.tick - BAR_ONE for e in region.events if e.pitch == KICK_NOTE)
        self.assertEqual(ticks, [round(b * 4) * SIXTEENTH for b in self.KICK_BEATS])
        self.assertTrue(all((e.tick - BAR_ONE) % SIXTEENTH == 0 for e in region.events))
        self.assertIn("1/16", "\n".join(report.lines()))
        self.assertEqual((validate_project(out), regressions(self.base, out)), ([], []))

    def test_a_note_quantized_onto_the_next_bar_line_widens_the_region(self):
        base = self.session([0.02, 7.97], [0.8, 0.8], kick_name="late.wav")
        free, free_report = self.run_it(base)
        snapped, report = self.run_it(base, grid=16)
        self.assertLessEqual(abs(self.new_region(base, free).events[-1].tick - BAR_ONE - round(7.97 * PPQ)), TOLERANCE)
        self.assertEqual(max(e.tick for e in self.new_region(base, snapped).events), BAR_ONE + 2 * BAR)
        self.assertEqual((free_report.bars, report.bars), (2, 3))
        self.assertEqual(regressions(base, snapped), [])

    def test_the_gm_map(self):
        out, _ = self.run_it(map_name="gm", hits=[(KICK, "kick"), (SNARE, "snare electric")])
        self.assertEqual(sorted({e.pitch for e in self.new_region(self.base, out).events}), [36, 40])

    def test_a_tempo_change_or_ramp_is_refused(self):
        for name, data in {"step": add_tempo(self.base, BAR_ONE + 2 * BAR, self.bpm + 20),
                           "ramp": add_ramp(self.base, BAR_ONE + BAR, self.bpm, BAR_ONE + 2 * BAR, self.bpm + 20)}.items():
            with self.subTest(name), self.assertRaisesRegex(ValueError, "changes tempo"):
                self.run_it(data)

    def test_refusals(self):
        cases = {
            "no gm drum map term 'kik'": dict(hits=[(KICK, "kik")], map_name="gm"),
            "more than once": dict(hits=[(KICK, "kick"), (KICK, "snare")]),
            "more than one track": dict(hits=[(KICK, "kick"), (SNARE, "kick")]),
            "no audio regions on 'Audio 3'": dict(hits=[("Audio 3", "kick")]),
            "1/12": dict(grid=12),
        }
        for text, kw in cases.items():
            with self.subTest(text), self.assertRaisesRegex(ValueError, text):
                self.run_it(**kw)
        with self.assertRaisesRegex(ValueError, "an audio track"):
            drums_to_midi(self.base, hits=self.hits, target=SNARE, wav_of=self.wav_of)
        with self.assertRaisesRegex(ValueError, "no audio file"):
            drums_to_midi(self.base, hits=self.hits, target=TARGET, wav_of=lambda r: None)

    def test_audio_without_hits_is_refused_naming_the_tracks(self):
        silent = clicks(self.dir / "silent.wav", [], [], self.bpm)
        with self.assertRaisesRegex(ValueError, r"no hits .*'Audio 1', 'Audio 2'"):
            drums_to_midi(self.base, hits=self.hits, target=TARGET, wav_of=lambda r: silent)

    def test_a_click_on_the_first_sample_is_a_note(self):
        base = self.session([0.0, *self.KICK_BEATS[1:]], self.KICK_AMPS, kick_name="downbeat.wav")
        out, report = self.run_it(base, hits=[(KICK, "kick")])
        self.assertEqual(report.hits[0][3], len(self.KICK_BEATS))
        self.assertEqual(min(e.tick for e in self.new_region(base, out).events), BAR_ONE)

    def test_the_region_starts_at_the_bar_of_the_first_quantized_note(self):
        base = self.session([3.97, 5.0], [0.8, 0.8], kick_name="pickup.wav")
        out, report = self.run_it(base, hits=[(KICK, "kick")], grid=4)
        region = self.new_region(base, out)
        self.assertEqual((region.start, report.start_bar, report.bars), (BAR_ONE + BAR, 2, 1))
        self.assertEqual(sorted(e.tick for e in region.events), [BAR_ONE + BAR, BAR_ONE + BAR + PPQ])
        self.assertEqual(regressions(base, out), [])

    def test_a_threshold_lower_than_the_default_keeps_a_quiet_hit(self):
        base = self.session([0.02, 1.0, 2.0], [0.8, 0.8 * 10 ** (-25 / 20), 0.8], kick_name="ghost.wav")
        _, default = self.run_it(base, hits=[(KICK, "kick")])
        _, low = self.run_it(base, hits=[(KICK, "kick")], detector=Detector(floor_db=-30))
        self.assertEqual((default.hits[0][3], low.hits[0][3]), (2, 3))

    def test_a_tracks_own_floor_applies_to_it_alone(self):
        base = self.session([0.02, 1.0, 2.0], [0.8, 0.8 * 10 ** (-25 / 20), 0.8], kick_name="ghost.wav")
        _, kick_low = self.run_it(base, floors={KICK: -30})
        _, snare_low = self.run_it(base, floors={SNARE: -30})
        self.assertEqual([(t, n) for t, _term, _note, n in kick_low.hits], [(KICK, 3), (SNARE, 2)])
        self.assertEqual([(t, n) for t, _term, _note, n in snare_low.hits], [(KICK, 2), (SNARE, 2)])
        self.assertIn(f"{KICK}: 3 hit(s) -> kick (note 36, addictive-drums-2); floor -30 dB", kick_low.lines())
        with self.assertRaisesRegex(ValueError, "no --hit names"):
            self.run_it(base, floors={"Audio 3": -30})

    def test_the_velocity_band_maps_the_quietest_and_loudest_hits_onto_it(self):
        out, report = self.run_it(velocity=(40, 100, 1.0))
        events = sorted(self.new_region(self.base, out).events, key=lambda e: e.tick)
        kicks = [e.velocity for e in events if e.pitch == KICK_NOTE]
        self.assertEqual((min(kicks), max(kicks)), (40, 100))
        self.assertEqual([e.velocity for e in events if e.pitch == SNARE_NOTE], [40, 100])
        self.assertIn("velocities 40..100", "\n".join(report.lines()))
        curved, _ = self.run_it(velocity=(40, 100, 2.0))
        bent = sorted(e.velocity for e in self.new_region(self.base, curved).events if e.pitch == KICK_NOTE)
        self.assertEqual((bent[0], bent[-1]), (40, 100))
        self.assertLess(sum(bent), sum(sorted(kicks)))
        with self.assertRaisesRegex(ValueError, "gamma above 0"):
            self.run_it(velocity=(40, 100, 0.0))

    def test_a_region_starting_inside_its_file_takes_only_the_hits_it_plays(self):
        spb = RATE * 60 / self.bpm
        data = reframed(self.base, 0, offset=round(2 * spb), frames=round(4 * spb))
        self.assertIn((KICK, round(2 * spb), round(4 * spb)), [(r.track, r.offset, r.frames) for r in read_audio_regions(data)])
        out, report = self.run_it(data, hits=[(KICK, "kick")])
        got = sorted(e.tick - BAR_ONE for e in self.new_region(data, out).events)
        want = [round((b - 2) * PPQ) for b in self.KICK_BEATS if 2 <= b < 6]
        self.assertEqual(len(got), len(want), got)
        self.assertTrue(all(abs(g - w) <= TOLERANCE for g, w in zip(got, want, strict=True)), (got, want))
        self.assertEqual(regressions(data, out), [])

    def test_a_region_cut_just_after_an_onset_keeps_that_hit_whole(self):
        spb = RATE * 60 / self.bpm
        loud, frames = round(spb), 4 * RATE
        wav = self.dir / "take.wav"
        write_wav(wav, slow_track([(round(spb / 2), 0.5), (loud, 0.9), (round(2.5 * spb), 0.5)], frames))
        shutil.copy(wav, self.dir / "take-b.wav")
        whole, _ = add_audio_region(self.golden, track=KICK, start=BAR_ONE, media_folder=self.media, wav=wav)
        for cut in (24, 100):
            with self.subTest(cut):
                cut_at = loud + cut
                data, _ = add_audio_region(whole, track=KICK, start=BAR_ONE + round(cut_at * PPQ / spb),
                                           media_folder=self.media, wav=self.dir / "take-b.wav")
                data = reframed(reframed(data, 1, offset=cut_at, frames=frames - cut_at), 0, offset=0, frames=cut_at)
                self.assertEqual([(r.offset, r.frames) for r in read_audio_regions(data)], [(0, cut_at), (cut_at, frames - cut_at)])
                for before in (whole, data):
                    after, _ = self.run_it(before, hits=[(KICK, "kick")])
                    events = sorted(self.new_region(before, after).events, key=lambda e: e.tick)
                    self.assertEqual([e.velocity for e in events], [1, 127, 1])

    def test_a_wav_at_another_rate_than_its_record_is_refused(self):
        (self.dir / "48k").mkdir()
        other = riff(self.dir / "48k" / "kick.wav", 3, 32, struct.pack("<4800f", *[0.0] * 4800))
        with self.assertRaisesRegex(ValueError, r"kick\.wav.*48000 Hz.*44100 Hz"):
            drums_to_midi(self.base, hits=[(KICK, "kick")], target=TARGET, wav_of=lambda r: other)

    def test_the_command_writes_a_copy(self):
        bundle = self.dir / "in" / "song.logicx"
        shutil.copytree(_goldens.path(GOLDEN), bundle)
        (bundle / "Alternatives" / "000" / "ProjectData").write_bytes(self.base)
        rc, printed = command([str(bundle), "--out", str(self.dir / "out"), "--hit", f"{KICK}=kick:-30",
                               "--hit", f"{SNARE}=snare", "--track", TARGET, "--grid", "16", "--velocity", "40..100"])
        self.assertEqual(rc, 0, printed)
        self.assertIn("Audio 1: 8 hit(s) -> kick (note 36, addictive-drums-2); floor -30 dB", printed)
        self.assertIn("velocities 40..100", printed)
        (written,) = (self.dir / "out").rglob("Alternatives/000/ProjectData")
        out = written.read_bytes()
        self.assertEqual(len(self.new_region(self.base, out).events), 10)
        self.assertEqual(bundle.joinpath("Alternatives", "000", "ProjectData").read_bytes(), self.base)

    def test_the_command_refuses_an_unknown_term_or_a_threshold_above_the_peak_before_copying(self):
        for flags, text in (([f"{KICK}=kik"], "no addictive-drums-2 drum map term 'kik'"), ([f"{KICK}=kick", "--threshold", "6"], "--threshold")):
            with self.subTest(text):
                rc, printed = command(["nowhere.logicx", "--out", str(self.dir / "out"), "--hit", *flags, "--track", TARGET])
                self.assertEqual(rc, 2)
                self.assertIn(text, printed)
                self.assertFalse((self.dir / "out").exists())


@_goldens.needs("signature-meter-3-4-logic")
class ThreeFourTest(unittest.TestCase):
    def test_the_bars_and_the_grid_are_the_projects_meter(self):
        golden = project_data(_goldens.path("signature-meter-3-4-logic"))
        with tempfile.TemporaryDirectory() as d:
            media = Path(d) / "Media"
            wav = clicks(Path(d) / "k.wav", [0.5, 2.8, 4.6, 5.97], [0.5, 0.6, 0.7, 0.8], project_tempo(golden)[1])
            data, _ = add_audio_region(golden, track="Audio 1", start=BAR_ONE, media_folder=media, wav=wav)
            for grid, bars, beats in ((None, 2, None), (2, 3, [0, 3, 5, 6])):
                with self.subTest(grid):
                    out, report = drums_to_midi(data, hits=[("Audio 1", "kick")], target="Inst 1", grid=grid,
                                                wav_of=lambda r: media / r.file.name)
                    (region,) = [r for r in read_midi(out) if r not in read_midi(data)]
                    (placed,) = [r for r in track_regions(out, "Inst 1") if r.start == region.start]
                    self.assertEqual((placed.length, report.bars), (bars * 3 * PPQ, bars))
                    if beats:
                        self.assertEqual(sorted(e.tick - BAR_ONE for e in region.events), [b * PPQ for b in beats])


@_goldens.needs("audio-three-regions-logic")
class OverlapTest(unittest.TestCase):
    def test_hits_that_overlapping_regions_share_count_once(self):
        golden = project_data(_goldens.path("audio-three-regions-logic"))
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            clicks(folder / "v030-tone2.wav", [0.5, 1.5, 3.0], [0.4, 0.9, 0.6], 120.0, seconds=2.0)
            clicks(folder / "v030-tone_1.wav", [0.5, 1.5], [0.4, 0.9], 120.0, seconds=1.0)
            out, report = drums_to_midi(golden, hits=[("Audio 3", "snare")], target=TARGET, wav_of=lambda r: folder / r.file.name)
            (region,) = [r for r in read_midi(out) if r not in read_midi(golden)]
            self.assertEqual((report.hits[0][3], report.merged, len(region.events)), (3, 0, 3))
            self.assertEqual(regressions(golden, out), [])


@_goldens.needs("songb-drums-to-midi-mine", "songb-drums-to-midi-logic")
class LogicResavedTest(unittest.TestCase):
    def test_logic_kept_the_region_and_every_note_written_over_a_real_take(self):
        from logicxkit.logic.services.project import project_metadata
        want = _goldens.fact("songb-drums-to-midi-mine", "regions")
        self.assertEqual([(r[0], len(r[2])) for r in want], [("Drums MIDI", 350)])
        for key in ("songb-drums-to-midi-mine", "songb-drums-to-midi-logic"):
            path = _goldens.path(key)
            data, count = project_data(path), project_metadata(path).get("tracks")
            self.assertEqual(validate_project(data), [])
            self.assertEqual([[r.name, r.start, [[e.tick, e.channel, e.pitch, e.velocity, e.length] for e in r.events]] for r in read_midi(data, count)], want)


if __name__ == "__main__":
    unittest.main()
