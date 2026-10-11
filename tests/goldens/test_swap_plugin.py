"""`swap-plugin` on public projects: every smart:comp 2 becomes a Compressor with its settings
carried, a crossing between families is refused slot by slot and the copy left as it was.
Skips without the public corpus."""

import contextlib
import io
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

import _goldens
from logicxkit.logic._swap_plugin_cmd import cmd_swap_plugin, matching_slots
from logicxkit.logic._edit import owner_by_label
from logicxkit.logic.services.mixer.plugins import slot_payloads
from logicxkit.logic.services.translate.translate import load_maps, map_for, read_settings
from logicxkit.logicx import project_data
from logicxkit.utils.data import PACKAGED

MAPS = load_maps([PACKAGED / "translate"])


def _swap(key: str, source: str, target: str, out: str | None, **more):
    args = Namespace(project=str(_goldens.path(key)), source=source, target=target, out=out, plan=out is None, channel=None,
                     stack=None, no_translate=False, keep_automation=False, set=None, library=str(PACKAGED / "donors"), force=False)
    for k, v in more.items():
        setattr(args, k, v)
    text = io.StringIO()
    with contextlib.redirect_stdout(text):
        code = cmd_swap_plugin(args)
    return code, text.getvalue()


def _slots(path: Path) -> dict[tuple[str, int], str]:
    return {(ref.channel, ref.key): ref.name for ref, _p in slot_payloads(project_data(path))}


@_goldens.needs("sonible-mono", "slots-named-mine")
class SwapTest(unittest.TestCase):
    def test_every_smart_comp_2_becomes_a_compressor_with_its_settings(self):
        source = project_data(_goldens.path("sonible-mono"))
        self.assertEqual([matching_slots(source, owner_by_label(source, c), "Soni/smC2", MAPS) for c in ("Audio 1", "Audio 2")], [[3], [3]])
        with tempfile.TemporaryDirectory() as tmp:
            code, out = _swap("sonible-mono", "Soni/smC2", "Compressor", tmp)
            self.assertEqual(code, 0, out)
            self.assertIn("Swapped 2 slot(s) on 2 channel(s).", out)
            copy = next(Path(tmp).glob("*.logicx"))
            data = project_data(copy)
            for channel in ("Audio 1", "Audio 2"):
                with self.subTest(channel):
                    ref, payload = next((r, p) for r, p in slot_payloads(data) if r.channel == channel and r.name == "Compressor")
                    values = read_settings(payload, map_for(payload, MAPS)).values
                    self.assertEqual((values["threshold"], values["attack"], values["release"]), (-15.0, 26.0, 150.0))
            self.assertNotIn("Soni/smC2", _slots(copy).values())
            before, after = _slots(_goldens.path("sonible-mono")), _slots(copy)
            self.assertEqual({k: v for k, v in before.items() if v != "Soni/smC2"}, {k: v for k, v in after.items() if v != "Compressor"})

    def test_a_plan_writes_nothing_and_a_crossing_between_families_is_refused(self):
        code, out = _swap("sonible-mono", "Soni/smC2", "Compressor", None)
        self.assertEqual(code, 0)
        self.assertIn("Would swap 2 slot(s) on 2 channel(s).", out)
        self.assertIn("Threshold = -15.0", out)
        with tempfile.TemporaryDirectory() as tmp:
            code, out = _swap("slots-named-mine", "Compressor", "Noise Gate", tmp)
            self.assertEqual(code, 0, out)
            self.assertIn("Swapped 0 slot(s) on 0 channel(s), 2 left as they are.", out)
            self.assertIn("Compressor is a compressor, Noise Gate a gate", out)
            copy = next(Path(tmp).glob("*.logicx"))
            self.assertEqual(_slots(copy), _slots(_goldens.path("slots-named-mine")))

    def test_without_translation_the_replacement_goes_in_at_its_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out = _swap("sonible-mono", "Soni/smC2", "Compressor", tmp, no_translate=True)
            self.assertEqual(code, 0, out)
            self.assertIn("Swapped 2 slot(s) on 2 channel(s).", out)
            self.assertIn("Compressor in, key 4 out", out)

    def test_a_plan_names_the_alternative_it_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            import shutil
            copy = Path(tmp) / "sonible-n03-mono.logicx"
            shutil.copytree(_goldens.path("sonible-mono"), copy)
            (copy / "Alternatives" / "000").rename(copy / "Alternatives" / "001")
            args = Namespace(project=str(copy), source="Soni/smC2", target="Compressor", out=None, plan=True, channel=None, stack=None,
                             no_translate=False, keep_automation=False, set=None, library=str(PACKAGED / "donors"), force=False)
            text = io.StringIO()
            with contextlib.redirect_stdout(text):
                cmd_swap_plugin(args)
            self.assertIn("  001: Audio 1", text.getvalue())

    def test_only_the_channels_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out = _swap("sonible-mono", "smart:comp 2", "Compressor", tmp, channel=["Audio 2"])
            self.assertEqual(code, 0, out)
            self.assertIn("Swapped 1 slot(s) on 1 channel(s).", out)
            slots = _slots(next(Path(tmp).glob("*.logicx")))
            self.assertEqual({c for (c, _k), n in slots.items() if n == "Soni/smC2"}, {"Audio 1"})


@_goldens.needs("swap-ours", "swap-resave-logic")
class LogicShowedTest(unittest.TestCase):
    def test_both_compressors_read_as_written_and_logic_kept_them(self):
        import re
        ours = project_data(_goldens.path("swap-ours"))
        shown = _goldens.entry("swap-resave-logic")["facts"]["shown"]
        for channel in ("Audio 1", "Audio 2"):
            _r, payload = next((r, p) for r, p in slot_payloads(ours) if r.channel == channel and r.name == "Compressor")
            values = read_settings(payload, map_for(payload, MAPS)).values
            for name, vocab in (("Threshold", "threshold"), ("Ratio", "ratio"), ("Attack", "attack"), ("Release", "release"), ("Make Up", "make_up"), ("Mix", "mix")):
                with self.subTest(channel=channel, name=name):
                    self.assertAlmostEqual(float(re.match(r"[-+]?\d+(?:\.\d+)?", shown[channel][name]).group()), values[vocab], places=3)
        self.assertEqual(_slots(_goldens.path("swap-ours")), _slots(_goldens.path("swap-resave-logic")))


@_goldens.needs("sonible-mono", "swap-packaged-ours", "swap-packaged-resave-logic")
class PackagedDonorsTest(unittest.TestCase):
    """The same swap with the package's donors only (2026-09-25): what a fresh install writes,
    and what Logic showed and kept of it."""

    def test_the_packaged_run_is_reproduced_from_its_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out = _swap("sonible-mono", "Soni/smC2", "Compressor", tmp)
            self.assertEqual(code, 0, out)
            self.assertEqual(project_data(next(Path(tmp).glob("*.logicx"))), project_data(_goldens.path("swap-packaged-ours")))

    def test_logic_showed_the_written_values_and_kept_them_with_the_donors_own_auto_release(self):
        import re
        ours, logic = (project_data(_goldens.path(k)) for k in ("swap-packaged-ours", "swap-packaged-resave-logic"))
        shown = _goldens.entry("swap-packaged-resave-logic")["facts"]["shown"]
        for channel in ("Audio 1", "Audio 2"):
            for data in (ours, logic):
                _r, payload = next((r, p) for r, p in slot_payloads(data) if r.channel == channel and r.name == "Compressor")
                values = read_settings(payload, map_for(payload, MAPS)).values
                for name, vocab in (("Threshold", "threshold"), ("Ratio", "ratio"), ("Attack", "attack"), ("Release", "release"), ("Make Up", "make_up"), ("Mix", "mix")):
                    with self.subTest(channel=channel, name=name):
                        self.assertAlmostEqual(float(re.match(r"[-+]?\d+(?:\.\d+)?", shown[channel][name]).group()), values[vocab], places=3)
            self.assertEqual(shown[channel]["Auto Release"], "1")            # the packaged #default donor's, where Drum Mix's read 0
        self.assertEqual(_slots(_goldens.path("swap-packaged-ours")), _slots(_goldens.path("swap-packaged-resave-logic")))


@_goldens.needs("snap-ours")
class RefusedSwapTest(unittest.TestCase):
    def test_a_name_no_slot_holds_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out = _swap("snap-ours", "Nope", "Compressor", tmp)
            self.assertEqual(code, 1, out)
            self.assertIn("no slot holds 'Nope'", out)
            self.assertIn("Compressor", out)                  # what the project does hold
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_a_plug_in_into_itself_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out = _swap("snap-ours", "Compressor", "154", tmp)
            self.assertEqual(code, 1, out)
            self.assertIn("the same plug-in", out)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    @_goldens.needs("instrument-studio-bass-logic")
    def test_an_id_several_plug_ins_share_is_refused(self):
        for source, named in (("InWr", "5 plug-ins (Studio Bass, Studio Horns, Studio Piano, Studio Strings, Vintage Mellotron)"),
                              ("147", "2 plug-ins (Echo, Tape Delay)")):
            with self.subTest(source), tempfile.TemporaryDirectory() as tmp:
                code, out = _swap("instrument-studio-bass-logic", source, "Studio Piano", tmp, no_translate=True)
                self.assertEqual(code, 1, out)
                self.assertIn(f"--from {source} names {named}; name the one to replace", out)
                self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_without_translation_a_dropped_side_chain_is_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out = _swap("snap-ours", "Noise Gate", "Compressor", tmp, no_translate=True)
            self.assertEqual(code, 0, out)
            self.assertIn("side chain Bus 1 dropped with the old plug-in", out)


@_goldens.needs("inserts-native-logic", "instrument-fx-io-logic", "instrument-quick-sampler-logic", "addtrack-order-mine",
                "auto-lanes-resave-logic")
class PlanAsWrittenTest(unittest.TestCase):
    """A plan leaves a slot as it is wherever the write would: an instrument into an effect slot,
    an effect into an instrument channel's slot 1; it swaps what the write swaps on an input with a
    flaw of its own and in every current alternative, and refuses a bundle the write refuses."""

    def test_every_current_alternative_is_planned_as_it_is_written(self):
        """Two Compressors on Audio 2, the alternative copied: four slots, plan and write."""
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "two.logicx"
            shutil.copytree(_goldens.path("auto-lanes-resave-logic"), project)
            shutil.copytree(project / "Alternatives" / "000", project / "Alternatives" / "001")
            for plan in (True, False):
                with self.subTest(plan=plan):
                    code, out = _swap("auto-lanes-resave-logic", "Compressor", "Noise Gate", None if plan else str(Path(tmp) / "out"),
                                      no_translate=True, project=str(project))
                    self.assertEqual(code, 0, out)
                    self.assertIn("000: Audio 2", out)
                    self.assertIn("001: Audio 2", out)
                    self.assertIn(f"{'Would swap' if plan else 'Swapped'} 4 slot(s) on 1 channel(s).", out)

    def test_an_inputs_own_flaw_is_tolerated_by_the_plan_as_by_the_write(self):
        from logicxkit.logic.services.stream.validate import validate_project
        self.assertTrue(validate_project(project_data(_goldens.path("addtrack-order-mine"))))
        for plan in (True, False):
            with self.subTest(plan=plan), tempfile.TemporaryDirectory() as tmp:
                code, out = _swap("addtrack-order-mine", "Multipressor", "Compressor", None if plan else tmp, no_translate=True)
                self.assertEqual(code, 0, out)
                self.assertIn(f"{'Would swap' if plan else 'Swapped'} 2 slot(s) on 2 channel(s).", out)

    def test_a_bundle_the_write_refuses_is_refused_by_the_plan(self):
        import shutil
        import struct
        from _cli import wrapped
        config = Path(__file__).resolve().parents[2] / "config" / "example-mastering.json"
        with tempfile.TemporaryDirectory() as tmp:
            older = Path(tmp) / "older.logicx"
            shutil.copytree(_goldens.path("inserts-native-logic"), older)
            data = older / "Alternatives" / "000" / "ProjectData"
            raw = bytearray(data.read_bytes())
            struct.pack_into("<H", raw, 4, 2000)                  # an earlier Logic's file format
            data.write_bytes(bytes(raw))
            for command in (("swap-plugin", older, "--from", "Compressor", "--to", "Noise Gate", "--no-translate"),
                            ("tracking-chains", older), ("chains", older, "--config", config),
                            ("apply-template", _goldens.path("inserts-native-logic"), older)):
                for run in (("--plan",), ("--out", Path(tmp) / "out")):
                    with self.subTest(command[0], plan=run == ("--plan",)):
                        code, out = wrapped(*command, *run)
                        self.assertEqual(code, 1, out)
                        self.assertIn("saved by an earlier Logic", out)
                        self.assertFalse((Path(tmp) / "out").exists())

    def test_the_plan_and_the_write_refuse_the_same_slots(self):
        from logicxkit.logic.services.mixer.donors import harvest_donors
        with tempfile.TemporaryDirectory() as library:
            harvest_donors(project_data(_goldens.path("instrument-quick-sampler-logic")), Path(library))
            for key, source, target, lib, why in (
                    ("inserts-native-logic", "Compressor", "Quick Sampler", library,
                     "an instrument goes into an instrument channel's slot 1, not into an audio effect slot"),
                    ("instrument-fx-io-logic", "I/O", "Quick Sampler", library,
                     "an instrument goes into slot 1 of an instrument channel, not slot 2"),
                    ("instrument-quick-sampler-logic", "Quick Sampler", "Compressor", str(PACKAGED / "donors"),
                     "slot 1 of an instrument channel is its instrument")):
                for plan in (True, False):
                    with self.subTest(key, plan=plan), tempfile.TemporaryDirectory() as tmp:
                        code, out = _swap(key, source, target, None if plan else tmp, no_translate=True, library=lib)
                        self.assertEqual(code, 0, out)
                        self.assertIn(f"left as it is — {why}", out)
                        self.assertIn(f"{'Would swap' if plan else 'Swapped'} 0 slot(s) on 0 channel(s), 1 left as they are", out)


if __name__ == "__main__":
    unittest.main()
