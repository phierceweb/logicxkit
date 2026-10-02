"""`tracking-chains` on public projects: third-party slots become their natives with the
settings carried, a plug-in of several families becomes one native per live family, a
plug-in without a native analogue is removed (or kept), natives carrying lookahead are
bypassed. Skips without the public corpus."""

import contextlib
import io
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

import _goldens
from logicxkit.logic._edit import owner_by_label
from logicxkit.logic._tracking_chains_cmd import cmd_tracking_chains
from logicxkit.logic.services.slots import slot_bypassed
from logicxkit.logic.services.stream import HEADER
from logicxkit.logic.services.plugins import slot_payloads
from logicxkit.logic.services.translate import load_maps, map_for, read_settings
from logicxkit.logic.services.transplant import channel_slots
from logicxkit.logicx import project_data
from logicxkit.utils.data import PACKAGED

MAPS = load_maps([PACKAGED / "translate"])


def _run(key: str, out: str | None, **more):
    args = Namespace(project=str(_goldens.path(key)), out=out, plan=out is None, channel=None, stack=None, keep_unmapped=False,
                     keep_lookahead=False, library=str(PACKAGED / "donors"))
    for k, v in more.items():
        setattr(args, k, v)
    text = io.StringIO()
    with contextlib.redirect_stdout(text):
        code = cmd_tracking_chains(args)
    return code, text.getvalue()


def _chain(data: bytes, label: str) -> list[tuple[str, bool]]:
    names = {(r.channel, r.key): r.name for r, _p in slot_payloads(data)}
    return [(names[(label, r.key)], slot_bypassed(r.raw)) for r in channel_slots(data, owner_by_label(data, label))]


@_goldens.needs("sonible-mono", "neutron-dialled", "stockfx-eq-defaults")
class TrackingChainsTest(unittest.TestCase):
    def test_sonibles_become_natives_and_the_lookahead_natives_are_bypassed(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out = _run("sonible-mono", tmp)
            self.assertEqual(code, 0, out)
            self.assertIn("Made native: 8 bypassed, 4 swapped.", out)
            data = project_data(next(Path(tmp).glob("*.logicx")))
            self.assertEqual(_chain(data, "Audio 1"), [("Compressor", False), ("Noise Gate", False), ("Linear Phase EQ", True),
                                                       ("Multipressor", True), ("Adaptive Limiter", True), ("Limiter", True)])
            self.assertEqual(_chain(data, "Audio 2"), [("Compressor", False), ("Noise Gate", False)])
            source = next(p for r, p in slot_payloads(project_data(_goldens.path("sonible-mono"))) if r.channel == "Audio 2" and r.name == "Soni/sGat")
            gate = next(p for r, p in slot_payloads(data) if r.channel == "Audio 2" and r.name == "Noise Gate")
            for name in ("attack", "hold", "release"):                # smart:gate's, carried onto the Noise Gate's slider positions
                want = read_settings(source, map_for(source, MAPS)).values[name]
                self.assertAlmostEqual(read_settings(gate, map_for(gate, MAPS)).values[name], want, delta=0.5 + want * 0.02)

    def test_neutron_becomes_a_channel_eq_and_a_compressor_after_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out = _run("neutron-dialled", tmp)
            self.assertEqual(code, 0, out)
            self.assertIn("Neutron 5's compressor -> Compressor, added after it", out)
            data = project_data(next(Path(tmp).glob("*.logicx")))
            self.assertEqual([n for n, _b in _chain(data, "Audio 2")], ["Compressor", "Noise Gate", "Compressor", "Channel EQ", "Compressor"])
            slots = channel_slots(data, owner_by_label(data, "Audio 2"))
            eq, comp = slots[3].raw[HEADER:], slots[4].raw[HEADER:]
            self.assertEqual([b.label() for b in read_settings(eq, map_for(eq, MAPS)).bands if b.on],
                             ["bell 150 Hz -4.0 dB Q 1.50", "bell 3.00 kHz -6.0 dB Q 4.00", "high shelf 2.00 kHz +3.0 dB Q 2.00"])
            self.assertEqual(read_settings(comp, map_for(comp, MAPS)).values["threshold"], -20.0)

    def test_a_plug_in_without_a_native_analogue_is_removed_unless_kept(self):
        before = _chain(project_data(_goldens.path("stockfx-eq-defaults")), "Audio 2")
        self.assertIn("iZtp/ZAZH", [n for n, _b in before])
        with tempfile.TemporaryDirectory() as tmp:
            code, out = _run("stockfx-eq-defaults", tmp, channel=["Audio 2"])
            self.assertEqual(code, 0, out)
            self.assertIn("iZtp/ZAZH removed: no native analogue", out)
            after = _chain(project_data(next(Path(tmp).glob("*.logicx"))), "Audio 2")
            self.assertEqual([n for n, _b in after], [n for n, _b in before if n != "iZtp/ZAZH"])
        code, out = _run("stockfx-eq-defaults", None, channel=["Audio 2"], keep_unmapped=True)
        self.assertIn("iZtp/ZAZH kept: no native analogue", out)
        self.assertIn("Would make native:", out)


@_goldens.needs("mb-promb")
class MadeLatentTest(unittest.TestCase):
    """A Pro-MB becomes a Multipressor, which carries lookahead like the ones already there."""

    def test_the_multipressor_it_makes_is_bypassed_unless_kept(self):
        for keep in (False, True):
            with self.subTest(keep_lookahead=keep), tempfile.TemporaryDirectory() as tmp:
                code, out = _run("mb-promb", tmp, keep_lookahead=keep)
                self.assertEqual(code, 0, out)
                self.assertEqual(_chain(project_data(next(Path(tmp).glob("*.logicx"))), "Audio 3"), [("Multipressor", not keep)])
                self.assertEqual("Multipressor bypassed: it carries lookahead" in out.split("Audio 3", 1)[1].split("\n  000:", 1)[0], not keep)

    def test_the_plan_says_so(self):
        code, out = _run("mb-promb", None)
        self.assertEqual(code, 0, out)
        self.assertIn("slot 4: Multipressor bypassed: it carries lookahead", out.split("Audio 3", 1)[1])


@_goldens.needs("trk-neutron-ours", "trk-neutron-resave-logic", "trk-sonible-ours", "trk-sonible-resave-logic")
class LogicShowedTest(unittest.TestCase):
    def test_the_derived_eq_and_compressor_read_as_written_and_the_bypasses_were_kept(self):
        import re
        data = project_data(_goldens.path("trk-neutron-ours"))
        self.assertEqual([n for n, _b in _chain(data, "Audio 2")], _goldens.entry("trk-neutron-ours")["facts"]["chain"])
        shown = _goldens.entry("trk-neutron-resave-logic")["facts"]["shown"]
        slots = channel_slots(data, owner_by_label(data, "Audio 2"))
        eq, comp = slots[3].raw[HEADER:], slots[4].raw[HEADER:]
        bands = {b.shape: b for b in read_settings(eq, map_for(eq, MAPS)).bands if b.on}
        self.assertEqual((bands["high_shelf"].frequency, bands["high_shelf"].gain), (2000.0, 3.0))
        self.assertEqual(shown["Channel EQ"]["High Shelf Gain"], "+3.0 dB")
        values = read_settings(comp, map_for(comp, MAPS)).values
        for name, vocab in (("Threshold", "threshold"), ("Ratio", "ratio"), ("Attack", "attack"), ("Release", "release"), ("Make Up", "make_up"), ("Mix", "mix")):
            with self.subTest(name):
                self.assertAlmostEqual(float(re.match(r"[-+]?\d+(?:\.\d+)?", shown["Compressor@3"][name]).group()), values[vocab], places=3)
        for key in ("trk-sonible-ours", "trk-sonible-resave-logic"):
            data = project_data(_goldens.path(key))
            for label, chain in _goldens.entry(key)["facts"]["chains"].items():
                with self.subTest(key=key, label=label):
                    self.assertEqual(_chain(data, label), [tuple(x) for x in chain])


if __name__ == "__main__":
    unittest.main()
