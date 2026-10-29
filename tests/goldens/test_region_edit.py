"""Region edits held to Logic's own single-change saves of one blank-born project (2026-09-15,
the `regions-a*` goldens): each of ours is written onto the save before Logic's and read back the same, with
the same song-container entries (their edited and selected marks aside)."""

import struct
import tempfile
import unittest
from pathlib import Path

import _goldens
from logicxkit.logic.services.regions.audio_regions import read_audio_files, region_key
from logicxkit.logic.services.regions.audio_write import add_audio_region
from logicxkit.logic.services.song.events import BAR_ONE
from logicxkit.logic.services.regions.fades import Fade, crossfade_bytes
from logicxkit.logic.services.stream.stream import HEADER, project_records
from logicxkit.logic.services.midi.midi import ENTRY_LOOP_LENGTH_AT
from logicxkit.logic.services.regions.region_edit import (
    move_region, rename_region, set_fade, set_loop, set_mute, split_region, trim_region,
)
from logicxkit.logic.services.regions.region_locate import listed, located, samples_per_tick_of
from logicxkit.logic.services.regions.regions import ENTRY, song_container
from logicxkit.logic.services.arrange.tracklist import arrange_run
from logicxkit.logic.services.stream.validate import validate_project
from logicxkit.logicx import project_data
from _region_edit import A, BAR, BEAT, RATE, Like, LikeLogic, entries, facts, load, number, region_counts, tone


@_goldens.needs(*(A[k] for k in range(0, 7)))
class AudioEditsTest(Like):
    def test_move_start_trim_end_trim_split_mute_rename(self):
        base = load(0)
        spt = samples_per_tick_of(base, RATE)
        n = number(base, "v030-tone")
        moved = move_region(base, n, BAR_ONE + BAR)
        self.like(moved, load(1), base, moved=[located(base, n).key])
        trimmed = trim_region(load(1), n, start=BAR_ONE + BAR + BEAT, spt=spt)
        self.like(trimmed, load(2), load(1), moved=[located(load(1), n).key])
        n2 = number(load(2), "v030-tone2")
        lengthened = trim_region(load(2), n2, length=3 * BEAT, spt=spt)
        self.like(lengthened, load(3), load(2), moved=[located(load(2), n2).key])
        split = split_region(load(3), n2, BAR_ONE + 2 * BEAT, spt=spt)
        self.like(split, load(4), load(3), moved=[located(load(3), n2).key])
        self.assertEqual([region_key(r.raw) for r in project_records(split) if r.tag == b"gRuA"],
                         [region_key(r.raw) for r in project_records(load(4)) if r.tag == b"gRuA"])
        self.assertEqual(region_counts(split), region_counts(load(4)))
        self.assertEqual(region_counts(load(4)), {"v030-tone.wav": 1, "v030-tone_1.wav": 1, "v030-tone2.wav": 2})
        muted = set_mute(load(4), number(load(4), "v030-tone_1"), True)
        self.like(muted, load(5), load(4))
        renamed = rename_region(load(5), number(load(5), "v030-tone_1"), "tone renamed")
        self.like(renamed, load(6), load(5))

    def test_the_pieces_of_logics_split_read_their_own_records(self):
        pieces = [(r.name, r.offset, r.frames, r.piece) for loc in listed(load(4)) if loc.audio and loc.region.name.startswith("v030-tone2")
                  for r in (loc.audio,)]
        self.assertEqual(pieces, [("v030-tone2", 0, 44100, 0), ("v030-tone2.1", 44100, 22050, 1)])


@_goldens.needs(*(A[k] for k in range(6, 15)))
class MidiEditsAndLoopsTest(Like):
    def test_move_end_trim_start_trim(self):
        n = number(load(6), "Inst 1", "midi")
        moved = move_region(load(6), n, BAR_ONE + 3 * BAR)
        self.like(moved, load(7), load(6), moved=[located(load(6), n).key])
        trimmed = trim_region(load(7), n, length=3 * BEAT)
        self.like(trimmed, load(8), load(7))
        start = trim_region(load(8), n, start=BAR_ONE + 3 * BAR + BEAT)
        self.like(start, load(9), load(8), moved=[located(load(8), n).key])

    def test_a_midi_split_keeps_the_events_and_plays_the_piece_from_the_cut(self):
        n = number(load(9), "Inst 1", "midi")
        split = split_region(load(9), n, BAR_ONE + 3 * BAR + 2 * BEAT)
        self.like(split, load(10), load(9), moved=[located(load(9), n).key], slots=False)
        pieces = [(r.midi.offset, tuple(e.tick for e in r.midi.events)) for r in listed(split) if r.midi]
        self.assertEqual(pieces, [(0, (49920, 51840)), (960, (49920, 51840))])
        self.assertEqual(pieces, [(r.midi.offset, tuple(e.tick for e in r.midi.events)) for r in listed(load(10)) if r.midi])

    def test_loops_on_and_off_write_the_length_word(self):
        n = number(load(10), "Inst 1", "midi")
        on = set_loop(load(10), n, True)
        self.like(on, load(11), load(10))
        self.assertEqual({struct.unpack_from("<I", e, ENTRY_LOOP_LENGTH_AT)[0] for e in entries(on)}, {960, 0x3FFFFFFF})
        self.like(set_loop(load(11), n, False), load(12), load(11))
        spt = samples_per_tick_of(load(12), RATE)
        m = number(load(12), "v030-tone")
        self.like(set_loop(load(12), m, True, spt=spt), load(13), load(12))
        self.assertEqual({struct.unpack_from("<I", e, ENTRY_LOOP_LENGTH_AT)[0] for e in entries(load(13))}, {960000, 0x3FFFFFFF})
        self.like(set_loop(load(13), m, False, spt=spt), load(14), load(13))


@_goldens.needs(*(A[k] for k in range(14, 21)))
class FadesTest(Like):
    def test_each_fade_field_against_logics_inspector(self):
        n = number(load(14), "tone renamed")
        steps = ((14, 15, Fade(in_ms=500)), (15, 16, Fade(in_ms=500, in_curve=50)), (16, 17, Fade(500, 50, 0, 500)),
                 (17, 19, Fade(500, 50, 0, 500, 30)), (19, 18, Fade(500, 50, 1, 500, 30)))
        for before, after, fade in steps:
            with self.subTest(after):
                self.like(set_fade(load(before), n, fade), load(after), load(before))
        self.assertEqual(located(load(18), n).audio.fade, Fade(500, 50, 1, 500, 30))

    def test_the_crossfade_save_reads_its_raw_bytes(self):
        data = load(20)
        under, over = (located(data, number(data, name)).audio for name in ("tone renamed", "v030-tone2.1"))
        records = project_records(data)
        p = records[song_container(records, arrange_run(records, None)).end].raw[HEADER:]
        self.assertEqual((crossfade_bytes(p[under.at:under.at + ENTRY]), crossfade_bytes(p[over.at:over.at + ENTRY])),
                         (b"\x20\x05\xf9", b"\x80\x00\x00"))
        self.assertEqual((under.fade.out_curve, over.start), (0, BAR_ONE + BEAT))


@_goldens.needs(A[25], A[26], A[28], A[29], A[30])
class NamesTest(Like, LikeLogic):
    def test_an_import_named_outside_ascii_reads_like_logics(self):
        base, logic = load(25), load(26)
        with tempfile.TemporaryDirectory() as tmp:
            media = Path(tmp, "Media", "Audio Files")
            media.mkdir(parents=True)
            out, _report = add_audio_region(base, track="Audio 2", start=BAR_ONE + 8 * BAR,
                                            wav=tone(Path(tmp, "v040-é.wav")), media_folder=media)
            self.assertEqual([p.name for p in media.iterdir()], ["v040-é.wav"])
        self.assertEqual([f.name for f in read_audio_files(out)][-1], "v040-é.wav")
        self.assert_like(out, logic)

    def test_renames_outside_ascii_read_like_logics(self):
        n = number(load(28), "v040-é")
        self.like(rename_region(load(28), n, "Snare \U0001f941"), load(29), load(28))
        m = number(load(29), "Inst 1", "midi")
        self.like(rename_region(load(29), m, "Pad — é"), load(30), load(29))
        self.assertEqual([f.name for f in read_audio_files(load(30))][-3:], ["v040-é.wav", "v040-\U0001f941.wav", "v040-日本.wav"])


@_goldens.needs("regions-audio-edits-ours", "regions-audio-edits-resave-logic")
class LogicResavedAudioEditsTest(unittest.TestCase):
    def test_logic_kept_the_move_trim_split_mute_rename_loop_and_fades(self):
        ours, logic = (project_data(_goldens.path(k)) for k in ("regions-audio-edits-ours", "regions-audio-edits-resave-logic"))
        self.assertEqual((validate_project(ours), validate_project(logic)), ([], []))
        self.assertEqual(facts(ours), facts(logic))
        self.assertEqual(entries(ours), entries(logic))
        self.assertEqual(region_counts(logic), {"v030-tone.wav": 1, "v030-tone_1.wav": 1, "v030-tone2.wav": 2})
        got = {(r.kind, r.region.name): r for r in listed(logic)}
        self.assertEqual((got[("audio", "v030-tone")].audio.start, got[("audio", "v030-tone")].audio.offset), (BAR_ONE + BAR + BEAT, 22050))
        self.assertEqual((got[("audio", "v030-tone2.1")].audio.offset, got[("audio", "v030-tone2.1")].audio.frames, got[("audio", "v030-tone2.1")].audio.piece), (44100, 44100, 1))
        self.assertEqual((got[("audio", "tone renamed")].audio.muted, got[("audio", "tone renamed")].audio.fade), (True, Fade(500, 50, 1, 500, 30)))
        self.assertTrue(got[("midi", "Inst 1")].midi.loop)


@_goldens.needs("regions-midi-edits-ours", "regions-midi-edits-resave-logic", A[6])
class LogicResavedMidiEditsTest(unittest.TestCase):
    def test_logic_kept_the_move_trim_split_and_loops(self):
        ours, logic = (project_data(_goldens.path(k)) for k in ("regions-midi-edits-ours", "regions-midi-edits-resave-logic"))
        self.assertEqual((validate_project(ours), validate_project(logic)), ([], []))
        self.assertEqual(facts(ours), facts(logic))
        self.assertEqual(entries(ours), entries(logic))
        want = _goldens.fact("regions-midi-edits-ours", "regions")
        self.assertEqual([r["name"] for r in want][:2], ["Inst 1", "Inst 1"])
        pieces = [(r.midi.start, r.midi.offset, r.midi.loop, tuple(e.tick for e in r.midi.events)) for r in listed(logic) if r.midi]
        self.assertEqual(pieces, [(BAR_ONE + 3 * BAR + BEAT, 0, True, (49920, 51840)), (BAR_ONE + 3 * BAR + 2 * BEAT, BEAT, False, (49920, 51840))])
        self.assertTrue(next(r.audio.loop for r in listed(logic) if r.audio and r.audio.name == "v030-tone2"))


if __name__ == "__main__":
    unittest.main()
