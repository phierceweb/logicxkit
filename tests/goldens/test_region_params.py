"""The Region inspector's parameters, fade-out types, crossfade and colours read from Logic's
single-change saves (2026-09-15, the `regions-b*` goldens), and each writer held to the save Logic made of the same edit."""

import importlib.util
import unittest
from dataclasses import replace
from pathlib import Path

import _goldens
from logicxkit.logic.services.regions.audio_regions import read_audio_regions
from logicxkit.logic.services.stream.integrity import regressions
from logicxkit.logic.services.midi.midi import read_midi
from logicxkit.logic.services.regions.region_edit import listed, move_region, samples_per_tick_of, set_fade
from logicxkit.logic.services.regions.region_params import RegionParams
from logicxkit.logic.services.regions.region_params_write import overlapped, set_colour, set_crossfade, set_params
from logicxkit.logic.services.stream.validate import validate_project
from logicxkit.logicx import project_data

_spec = importlib.util.spec_from_file_location("goldens_region_edit", Path(__file__).with_name("test_region_edit.py"))
_region_edit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_region_edit)
entries = _region_edit.entries

A18, A20 = "regions-a18-fade-in-speed-up-logic", "regions-a20-crossfade-logic"
B = {k: f"regions-b{k:02d}-{name}-logic" for k, name in (
    (0, "base"), (1, "gain-plus-3"), (2, "gain-minus-6"), (3, "delay-plus-120"), (4, "transpose-plus-2"), (5, "fine-tune-plus-25"),
    (7, "gain-0"), (8, "fade-out-type-x"), (9, "fade-out-type-eqp"), (10, "fade-out-type-xs"), (11, "fade-out-type-out"),
    (15, "gain-plus-30"), (16, "gain-minus-30"), (17, "gain-minus-17"), (20, "transpose-minus-3"), (21, "fine-tune-minus-25"),
    (22, "delay-minus-120"), (23, "reverse-on"), (24, "reverse-off"), (25, "crossfade-curve-drag"), (26, "crossfade-curve-40"),
    (27, "crossfade-length-563"), (28, "crossfade-length-500"), (29, "underneath-moved-bar-2"), (31, "audio-colour-12"),
    (32, "midi-colour-40"))}
RATE = 44100


def load(k: int) -> bytes:
    return project_data(_goldens.path(B[k]))


def audio(data: bytes, name: str):
    return next(r for r in read_audio_regions(data) if r.name == name)


def number(data: bytes, name: str) -> int:
    return next(loc.number for loc in listed(data) if loc.region.name == name)


@_goldens.needs(*B.values())
class ReadTest(unittest.TestCase):
    def test_each_parameter_reads_what_the_inspector_showed(self):
        for k in (1, 2, 3, 4, 5, 7, 15, 16, 17, 20, 21, 22):
            facts = {f: v for f in ("gain", "delay", "transpose", "fine_tune") if (v := _goldens.fact(B[k], f)) is not None}
            with self.subTest(B[k]):
                params = audio(load(k), "tone renamed").params
                self.assertEqual({f: getattr(params, f) for f in facts}, facts)
        self.assertEqual((audio(load(23), "v030-tone").params.reverse, audio(load(24), "v030-tone").params.reverse), (True, False))
        self.assertEqual(audio(load(0), "tone renamed").params, RegionParams())

    def test_the_fade_out_types_and_the_crossfade(self):
        for k in (8, 9, 10, 11):
            with self.subTest(B[k]):
                self.assertEqual(audio(load(k), "tone renamed").fade.out_type, _goldens.fact(B[k], "out_type"))
        for k in (25, 26, 27, 28, 29):
            with self.subTest(B[k]):
                fade = audio(load(k), "tone renamed").fade
                self.assertEqual((fade.out_ms, fade.out_curve, fade.out_type),
                                 (_goldens.fact(B[k], "out_ms"), _goldens.fact(B[k], "out_curve", fade.out_curve), "eqp"))
        self.assertEqual(audio(load(29), "tone renamed").start_bar, 2.0)

    def test_colours(self):
        data = load(31)
        self.assertEqual((audio(data, "v030-tone").colour, audio(data, "tone renamed").colour), (36, 16))
        self.assertEqual([r.colour for r in read_midi(load(32))][0], 64)
        self.assertEqual([r.colour for r in read_midi(load(31))][0], 9)


@_goldens.needs(A18, A20, *B.values())
class LikeLogicTest(unittest.TestCase):
    """Ours written onto the save before Logic's, compared entry for entry (edited and selected marks aside)."""

    def held(self, before: int, after: int, write):
        data = load(before)
        out = write(data, number(data, "tone renamed"))
        self.assertEqual((validate_project(out), regressions(data, out)), ([], []))
        self.assertEqual(entries(out), entries(load(after)))
        return out

    def test_gain_delay_fine_tune_and_reverse_land_as_logic_wrote_them(self):
        params = lambda **kw: (lambda data, n: set_params(data, n, replace(audio(data, "tone renamed").params, **kw)))  # noqa: E731
        self.held(0, 1, params(gain=3))
        self.held(1, 2, params(gain=-6))
        self.held(2, 3, params(delay=120))
        self.held(4, 5, params(fine_tune=25))
        self.held(15, 16, params(gain=-30))
        self.held(16, 17, params(gain=-17))
        self.held(20, 21, params(fine_tune=-25))
        self.held(21, 22, params(delay=-120))
        data = load(22)
        n = number(data, "v030-tone")
        out = set_params(data, n, replace(audio(data, "v030-tone").params, reverse=True))
        self.assertEqual(entries(out), entries(load(23)))
        self.assertEqual(entries(set_params(out, n, replace(audio(out, "v030-tone").params, reverse=False))), entries(load(24)))

    def test_transpose_writes_the_field_logic_flexed_the_track_for(self):
        data = load(3)
        out = set_params(data, number(data, "tone renamed"), replace(audio(data, "tone renamed").params, transpose=2))
        self.assertEqual(audio(out, "tone renamed").params.transpose, 2)
        self.assertEqual(audio(load(4), "tone renamed").params.transpose, 2)
        self.assertNotEqual(entries(out), entries(load(4)))              # Logic added flex blocks and bits too

    def test_the_fade_out_types_and_curve_land_as_logic_wrote_them(self):
        fade = lambda **kw: (lambda data, n: set_fade(data, n, replace(audio(data, "tone renamed").fade, **kw)))  # noqa: E731
        self.held(7, 8, fade(out_type="x"))
        self.held(8, 9, fade(out_type="eqp"))
        self.held(9, 10, fade(out_type="xs"))
        self.held(10, 11, fade(out_type="out"))
        self.held(25, 26, fade(out_curve=40))

    def test_colour_lands_as_logic_wrote_it(self):
        data = load(29)
        n = number(data, "v030-tone")
        out = set_colour(data, n, 36)
        self.assertEqual((audio(out, "v030-tone").colour, regressions(data, out)), (36, []))
        record = lambda d: next(r for r in read_audio_regions(d) if r.name == "v030-tone").record  # noqa: E731
        from logicxkit.logic.services.stream.stream import project_records
        self.assertEqual(project_records(out)[record(out)].raw[36:76], project_records(load(31))[record(load(31))].raw[36:76])
        midi = number(load(31), "Inst 1")
        out = set_colour(load(31), midi, 64)
        self.assertEqual([r.colour for r in read_midi(out)][0], 64)
        self.assertEqual(regressions(load(31), out), [])

    def test_a_nudge_under_x_fade_recreated_from_the_save_before_matches_logics(self):
        """A18 (Logic's last save before A20) -> A20: the top region a beat left and the crossfade written; Logic's
        +68 (f9) is the one byte ours lacks."""
        data = project_data(_goldens.path(A18))
        spt = samples_per_tick_of(data, RATE)
        top = next(loc for loc in listed(data) if loc.region.name == "v030-tone2.1")
        out = move_region(data, top.number, top.region.start - 960)
        out = set_crossfade(out, number(out, "tone renamed"), ms=None, curve=0, kind="eqp", spt=spt, rate=RATE)
        masked = lambda d: [e[:68] + b"\0" + e[69:] for e in entries(d)]  # noqa: E731
        self.assertEqual(masked(out), masked(project_data(_goldens.path(A20))))
        self.assertEqual((audio(out, "tone renamed").fade.out_ms, audio(out, "tone renamed").fade.out_type), (500, "eqp"))
        self.assertEqual((validate_project(out), regressions(data, out, removed=[top.key])), ([], []))

    def test_a_crossfade_written_onto_the_overlap_matches_logics_drag(self):
        data = load(0)
        spt = samples_per_tick_of(data, RATE)
        loc, top, overlap = overlapped(data, number(data, "tone renamed"), spt)
        self.assertEqual((top.name, round(overlap)), ("v030-tone2.1", 960))
        out = set_crossfade(data, number(data, "tone renamed"), ms=None, curve=0, kind="eqp", spt=spt, rate=RATE)
        self.assertEqual(entries(out), entries(data))
        self.assertEqual((validate_project(out), regressions(data, out)), ([], []))
        with self.assertRaisesRegex(ValueError, "no region starts inside it"):
            set_crossfade(data, number(data, "v030-tone"), ms=None, curve=0, kind="eqp", spt=spt, rate=RATE)
        with self.assertRaisesRegex(ValueError, "x, eqp or xs"):
            set_crossfade(data, number(data, "tone renamed"), ms=None, curve=0, kind="out", spt=spt, rate=RATE)
        with self.assertRaisesRegex(ValueError, "MIDI region"):
            set_crossfade(data, number(data, "Inst 1"), ms=None, curve=0, kind="eqp", spt=spt, rate=RATE)


@_goldens.needs("regions-params-ours", "regions-params-resave-logic")
class LogicResavedTest(unittest.TestCase):
    """The parameters, a fade-out type, a crossfade and two colours on one copy, re-saved by Logic: back as written."""

    def test_logic_kept_every_field(self):
        want = _goldens.fact("regions-params-ours", "regions")
        for key in ("regions-params-ours", "regions-params-resave-logic"):
            data = project_data(_goldens.path(key))
            with self.subTest(key):
                self.assertEqual(validate_project(data), [])
                by_name = {r.name: r for r in read_audio_regions(data)}
                midi = read_midi(data)
                for name, *fields in want:
                    if name not in by_name:
                        self.assertEqual(next(r.colour for r in midi if r.name == name), fields[0])
                        continue
                    r = by_name[name]
                    for field in fields:
                        if isinstance(field, int):
                            self.assertEqual(r.colour, field)
                        elif "gain" in field:
                            self.assertEqual({k: getattr(r.params, k) for k in field}, field)
                        else:
                            self.assertEqual({k: getattr(r.fade, k) for k in field}, field)
        ours, logic = (project_data(_goldens.path(k)) for k in ("regions-params-ours", "regions-params-resave-logic"))
        masked = lambda d: [e[:66] + b"\0" + e[67:] for e in entries(d)]  # noqa: E731
        self.assertEqual(masked(ours), masked(logic))


if __name__ == "__main__":
    unittest.main()
