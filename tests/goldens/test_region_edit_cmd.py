"""`logic regions` on copies: a region named by its listing number in every alternative, edits that keep
their numbers as the listing moves, aliases, loops, imports and the refusals. Skips without the corpus."""

import struct
import tempfile
import unittest
from pathlib import Path

import _goldens
from logicxkit.logic.services.song.events import BAR_ONE
from logicxkit.logic.services.stream.stream import HEADER, project_records
from logicxkit.logic.services.midi.midi import ENTRY_LOOP_LENGTH_AT
from logicxkit.logic.services.regions.region_edit import (
    move_region, rename_region, set_loop, set_mute, split_region, trim_region,
)
from logicxkit.logic.services.regions.region_locate import listed, located
from logicxkit.logic.services.regions.regions import song_container
from logicxkit.logic.services.arrange.tracklist import arrange_run
from logicxkit.logicx import project_data
from _region_edit import A, BAR, BEAT, aliased, entries, load, number, tone


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
        from logicxkit.logic.services.midi.midi_write import add_region
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
        from logicxkit.logic.services.midi.midi_write import add_region
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
        from logicxkit.logic.services.midi.midi import read_midi
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
        from logicxkit.logic.services.regions.flexmarkers import FLEX_BIT
        from logicxkit.logic.services.stream.recbuild import rec
        data = load(0)
        n = number(data, "v030-tone")
        records = project_records(data)
        song = song_container(records, arrange_run(records, None))
        p = bytearray(records[song.end].raw[HEADER:])
        p[located(data, n).audio.at + 15] |= FLEX_BIT
        out = [r.raw for r in records]
        out[song.end] = rec(b"qSvE", records[song.end].raw, bytes(p))
        from logicxkit.logic.services.stream.stream import reassemble
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


if __name__ == "__main__":
    unittest.main()
