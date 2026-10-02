"""Region edits held to Logic's own single-change saves of one blank-born project (2026-09-15,
the `regions-a*` goldens): each of ours is written onto the save before Logic's and read back the same, with
the same song-container entries (their edited and selected marks aside)."""

import importlib.util
import struct
import tempfile
import unittest
from pathlib import Path

import _goldens
from logicxkit.logic.services.audio_regions import FILE_TAG, REGION_COUNT_AT, file_name, magic_at, read_audio_files, region_key
from logicxkit.logic.services.audio_write import add_audio_region
from logicxkit.logic.services.events import BAR_ONE
from logicxkit.logic.services.fades import Fade, crossfade_bytes
from logicxkit.logic.services.stream import HEADER, project_records
from logicxkit.logic.services.integrity import regressions
from logicxkit.logic.services.midi import ENTRY_LOOP_LENGTH_AT
from logicxkit.logic.services.region_edit import (
    listed, located, move_region, rename_region, samples_per_tick_of, set_fade, set_loop, set_mute, split_region, trim_region,
)
from logicxkit.logic.services.regions import ENTRY, entry_offsets, song_container
from logicxkit.logic.services.tracklist import arrange_run
from logicxkit.logic.services.validate import validate_project
from logicxkit.logicx import project_data

_spec = importlib.util.spec_from_file_location("goldens_audio_write", Path(__file__).with_name("test_audio_write.py"))
_audio_write = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_audio_write)
LikeLogic, tone = _audio_write.LikeLogic, _audio_write.tone
_spec = importlib.util.spec_from_file_location("goldens_midi_edit", Path(__file__).with_name("test_midi_edit.py"))
_midi_edit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_midi_edit)
aliased = _midi_edit.aliased

BAR, BEAT, RATE = 3840, 960, 44100
A = {k: f"regions-a{k:02d}-{name}-logic" for k, name in (
    (0, "base"), (1, "audio-moved"), (2, "audio-start-trimmed"), (3, "audio-end-trimmed"), (4, "audio-split"),
    (5, "audio-muted"), (6, "audio-renamed"), (7, "midi-moved"), (8, "midi-end-trimmed"), (9, "midi-start-trimmed"),
    (10, "midi-split"), (11, "midi-loop-on"), (12, "midi-loop-off"), (13, "audio-loop-on"), (14, "audio-loop-off"),
    (15, "fade-in-500"), (16, "fade-in-curve-50"), (17, "fade-out-500"), (18, "fade-in-speed-up"), (19, "fade-out-curve-30"),
    (20, "crossfade"), (25, "marker-deleted".replace("marker-deleted", "import-e-acute")), (26, "import-e-acute"),
    (28, "import-kanji"), (29, "rename-emoji"), (30, "midi-rename"))}
A[25] = "markers-a25-deleted-logic"


def load(k: int) -> bytes:
    return project_data(_goldens.path(A[k]))


def facts(data: bytes) -> list[tuple]:
    out = []
    for loc in listed(data):
        r = loc.region
        row = (loc.kind, r.track, r.name, r.start, r.loop, r.muted)
        if loc.audio:
            row += (r.frames, r.offset, r.piece, r.file.name if r.file else None, r.fade)
        else:
            row += (tuple((e.tick, e.pitch, e.velocity, e.length) for e in r.events),)
        out.append(row)
    return out


def entries(data: bytes, slots: bool = True) -> list[bytes]:
    """The song container's entries, the edited and selected marks cleared, sorted; ``slots``
    False blanks the sequence slots (Logic's free-slot choice is not ours)."""
    records = project_records(data)
    p = records[song_container(records, arrange_run(records, None)).end].raw[HEADER:]
    out = []
    for off in entry_offsets(p):
        e = bytearray(p[off:off + ENTRY])
        e[13] &= ~0x01
        e[15] = 0
        if not slots:
            e[32:36] = bytes(4)
        out.append(bytes(e))
    return sorted(out)


def region_counts(data: bytes) -> dict[str, int]:
    """Each file record's region count, the word Logic loads that many regions by."""
    out = {}
    for r in project_records(data):
        if r.tag == FILE_TAG:
            p = r.raw[HEADER:]
            out[file_name(p)] = struct.unpack_from("<I", p, magic_at(p) + REGION_COUNT_AT)[0]
    return out


def number(data: bytes, name: str, kind: str = "audio", which: int = 0) -> int:
    return [loc.number for loc in listed(data) if loc.kind == kind and loc.region.name == name][which]


class Like(unittest.TestCase):
    def like(self, ours: bytes, logic: bytes, before: bytes, moved=(), slots: bool = True):
        self.assertEqual(validate_project(ours), [])
        self.assertEqual(regressions(before, ours, removed=moved), [])
        self.assertEqual(facts(ours), facts(logic))
        self.assertEqual(entries(ours, slots), entries(logic, slots))


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


def run(*argv) -> tuple[int, str]:
    import contextlib
    import io
    from logicxkit.cli import main
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = main(["logic", "regions", *map(str, argv)])
    return rc, out.getvalue()


def two_alternatives(key: str, tmp: Path, second) -> Path:
    """A copy of golden ``key`` with a second alternative, its ProjectData ``second(data)``."""
    import shutil
    bundle = tmp / f"{key}.logicx"
    shutil.copytree(_goldens.path(key), bundle)
    alts = sorted((bundle / "Alternatives").iterdir())
    other = bundle / "Alternatives" / "001"
    shutil.copytree(alts[0], other)
    (other / "ProjectData").write_bytes(second((other / "ProjectData").read_bytes()))
    return bundle


def alternatives(out: Path) -> dict[str, bytes]:
    (project,) = out.rglob("*.logicx")
    return {p.parent.name: p.read_bytes() for p in sorted(project.rglob("Alternatives/*/ProjectData"))}


@_goldens.needs(A[0])
class AlternativesTest(unittest.TestCase):
    def test_a_number_names_the_same_region_in_every_alternative(self):
        from logicxkit.logic.services.midi_write import add_region
        with tempfile.TemporaryDirectory() as tmp:
            bundle = two_alternatives(A[0], Path(tmp), lambda d: add_region(d, track="Untitled", start=BAR_ONE, length=BAR)[0])
            rc, text = run(bundle, "--out", Path(tmp, "out"), "--mute", "2")
            self.assertEqual(rc, 0, text)
            alts = alternatives(Path(tmp, "out"))
        self.assertEqual(sorted(alts), ["000", "001"])
        for alt, data in alts.items():
            with self.subTest(alt):
                muted = [(r.kind, r.region.name) for r in listed(data) if r.region.muted]
                self.assertEqual(muted, [("audio", "v030-tone")])

    def test_two_regions_alike_in_the_listed_alternative_are_told_apart_by_number(self):
        from logicxkit.logic.services.midi_write import add_region
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / "one.logicx"
            shutil.copytree(_goldens.path(A[0]), bundle)
            alt = sorted((bundle / "Alternatives").iterdir())[0] / "ProjectData"
            alt.write_bytes(add_region(alt.read_bytes(), track="Untitled", start=BAR_ONE + 2 * BAR, length=BAR, name="Inst 1")[0])
            self.assertEqual([r.region.name for r in listed(alt.read_bytes())][:2], ["Inst 1", "Inst 1"])
            rc, text = run(bundle, "--out", Path(tmp, "out"), "--mute", "1")
            self.assertEqual(rc, 0, text)
            (data,) = alternatives(Path(tmp, "out")).values()
        self.assertEqual([r.region.muted for r in listed(data)][:2], [True, False])

    def test_an_alternative_lacking_the_region_refuses_the_whole_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = two_alternatives(A[0], Path(tmp), lambda d: rename_region(d, number(d, "v030-tone"), "elsewhere"))
            rc, text = run(bundle, "--out", Path(tmp, "out"), "--mute", "2")
            self.assertEqual(rc, 1)
            self.assertIn("alternative 001 has no region 'v030-tone' on 'Audio 2' at bar 1", text)
            self.assertEqual(list(Path(tmp, "out").rglob("*.logicx")), [])       # the copy is discarded whole


@_goldens.needs(A[0], A[9], "tempo-point-140-logic")
class CommandTest(unittest.TestCase):
    def test_edits_keep_the_inputs_numbers_after_a_split_moves_the_listing(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, text = run(_goldens.path(A[0]), "--out", tmp, "--split", "3=1.5", "--move", "4=9")
            self.assertEqual(rc, 0, text)
            (project,) = Path(tmp).rglob("*.logicx")
            got = {(r.kind, r.region.name): r.region.start for r in listed(project_data(project))}
        self.assertEqual(got[("audio", "v030-tone_1")], BAR_ONE + 8 * BAR)      # the input's region 4, not the new piece
        self.assertEqual(got[("audio", "v030-tone2.1")], BAR_ONE + 2 * BEAT)

    def test_an_import_on_the_same_command_line_does_not_shift_the_numbers(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, text = run(_goldens.path(A[0]), "--out", tmp, "--audio", f"Audio 2:3:{tone(Path(tmp, 'v040-take.wav'))}", "--move", "3=5")
            self.assertEqual(rc, 0, text)
            (project,) = Path(tmp).rglob("*.logicx")
            got = {(r.kind, r.region.name): r.region.start for r in listed(project_data(project))}
        self.assertEqual((got[("audio", "v030-tone2")], got[("audio", "v040-take")]), (BAR_ONE + 4 * BAR, BAR_ONE + 2 * BAR))

    def test_aliases_take_a_mute_each_and_no_other_edit(self):
        from logicxkit.logic.services.midi import read_midi
        base = load(0)
        source = read_midi(base)[0]
        data = aliased(base, source, 4)
        self.assertEqual([r.slot for r in read_midi(data)], [source.slot] * 2)
        muted = set_mute(data, 2, True)
        self.assertEqual([r.muted for r in read_midi(muted)], [False, True])
        for act in (lambda: move_region(data, 2, BAR_ONE + 9 * BAR), lambda: trim_region(data, 2, length=BEAT),
                    lambda: split_region(data, 2, source.start + 4 * BAR + BEAT), lambda: set_loop(data, 2, True),
                    lambda: rename_region(data, 2, "x")):
            with self.assertRaisesRegex(ValueError, "one of 2 regions playing one sequence"):
                act()
        self.assertEqual([r.number for r in listed(data) if r.midi], [1, 2])
        self.assertEqual([r.ident for r in listed(data) if r.midi], [("midi", source.slot, 0), ("midi", source.slot, 1)])

    def test_a_trimmed_loop_keeps_its_loop_length_current(self):
        n = number(load(10), "Inst 1", "midi")
        looped = set_loop(load(10), n, True)
        trimmed = trim_region(looped, n, length=2 * BEAT)
        self.assertTrue(located(trimmed, n).midi.loop)
        self.assertIn(2 * BEAT, {struct.unpack_from("<I", e, ENTRY_LOOP_LENGTH_AT)[0] for e in entries(trimmed)})
        self.assertNotIn(BEAT, {struct.unpack_from("<I", e, ENTRY_LOOP_LENGTH_AT)[0] for e in entries(trimmed)})

    def test_a_song_whose_tempo_changes_still_takes_an_import_a_mute_and_a_rename(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, text = run(_goldens.path("tempo-point-140-logic"), "--out", tmp, "--audio", f"Audio 1:1:{tone(Path(tmp, 'v040-t.wav'))}")
            self.assertEqual(rc, 0, text)
            (project,) = Path(tmp).rglob("*.logicx")
            rc, text = run(project, "--out", Path(tmp, "b"), "--mute", "1", "--rename", "1=renamed")
            self.assertEqual(rc, 0, text)
            rc, text = run(project, "--out", Path(tmp, "c"), "--trim", "1=1:1")
            self.assertEqual(rc, 1)
            self.assertIn("the tempo changes", text)

    def test_a_flexed_region_is_not_trimmed_or_split(self):
        from logicxkit.logic.services.flexmarkers import FLEX_BIT
        from logicxkit.logic.services.recbuild import rec
        data = load(0)
        n = number(data, "v030-tone")
        records = project_records(data)
        song = song_container(records, arrange_run(records, None))
        p = bytearray(records[song.end].raw[HEADER:])
        p[located(data, n).audio.at + 15] |= FLEX_BIT
        out = [r.raw for r in records]
        out[song.end] = rec(b"qSvE", records[song.end].raw, bytes(p))
        from logicxkit.logic.services.stream import reassemble
        flexed = reassemble(data, out)
        for edit in (lambda: trim_region(flexed, n, length=BEAT, spt=22.96875), lambda: split_region(flexed, n, BAR_ONE + BEAT, spt=22.96875)):
            with self.assertRaisesRegex(ValueError, "is flexed"):
                edit()

    def test_a_start_trim_past_an_event_is_refused_not_a_traceback(self):
        n = number(load(9), "Inst 1", "midi")
        long = trim_region(load(9), n, length=20 * BAR)
        with self.assertRaisesRegex(ValueError, "would land before the sequence's start"):
            trim_region(long, n, start=BAR_ONE + 3 * BAR + BEAT + 11 * BAR)
        with self.assertRaisesRegex(ValueError, "at or after bar 1"):
            trim_region(long, n, start=BAR_ONE - BEAT)


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
