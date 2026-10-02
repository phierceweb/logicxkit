"""A Pro-C 2 at its defaults on Logic's own save reads the values FabFilter's window shows, and
plans a Compressor from them. Skips without the public corpus."""

import re
import unittest

import _goldens
from logicxkit.logic._edit import owner_by_label
from logicxkit.logic.services.stream import HEADER
from logicxkit.logic.services.transplant import channel_slots, slot_at
from logicxkit.logic.services.translate import load_maps, map_for, plan, read_settings
from logicxkit.logicx import project_data
from logicxkit.utils.data import PACKAGED


def _slot(key: str):
    data = project_data(_goldens.path(key))
    facts = _goldens.entry(key)["facts"]
    return facts, slot_at(data, owner_by_label(data, facts["channel"]), facts["slot"]).raw[HEADER:]


@_goldens.needs("translate-proc", "translate-ours", "translate-ours-resave-logic")
class DialledProC2Test(unittest.TestCase):
    """A Pro-C 2 dialled in Logic reads what its window showed; carried into a Compressor, Logic
    showed and kept the values on the Compressor's own grids."""

    def test_the_dialled_pro_c_2_reads_what_its_window_showed(self):
        facts, payload = _slot("translate-proc")
        maps = load_maps([PACKAGED / "translate"])
        s = read_settings(payload, map_for(payload, maps))
        for name, want in facts["shown"].items():
            with self.subTest(name):
                got = s.values[name]
                self.assertEqual(got, want) if isinstance(want, bool) else self.assertAlmostEqual(got, want, delta=0.01)

    def test_the_plan_lands_on_logic_own_grid(self):
        facts, payload = _slot("translate-proc")
        maps = load_maps([PACKAGED / "translate"])
        p = plan(read_settings(payload, map_for(payload, maps)), next(m for m in maps if m.plugin == "Compressor"))
        shown = _goldens.entry("translate-ours-resave-logic")["facts"]["shown"]
        for param in ("Threshold", "Ratio", "Make Up", "Knee", "Mix"):     # Logic showed and kept these as planned
            with self.subTest(param):
                self.assertAlmostEqual(p.values[param], float(re.match(r"-?\d+(?:\.\d+)?", shown[param]).group()), places=3)
        self.assertAlmostEqual(p.values["Attack"], 10.5, places=3)           # the knob's nearer position, what Logic showed
        self.assertAlmostEqual(p.values["Release"], 110.0, places=3)         # 115 sits between 110 and 120: down, what Logic showed

    def test_a_compressors_style_or_circuit_is_said_not_to_cross(self):
        _facts, payload = _slot("translate-proc")
        maps = load_maps([PACKAGED / "translate"])
        comp, proc = (next(m for m in maps if m.plugin == name) for name in ("Compressor", "Pro-C 2"))
        notes = " ".join(plan(read_settings(payload, map_for(payload, maps)), comp).notes)
        for word in ("style", "range", "hold", "lookahead", "auto_gain"):
            self.assertIn(word, notes)
        data = project_data(_goldens.path("translate-proc"))
        native = slot_at(data, owner_by_label(data, "Audio 2"), 1).raw[HEADER:]
        self.assertTrue(any("circuit" in n for n in plan(read_settings(native, map_for(native, maps)), proc).notes))

    def test_logic_kept_our_write_but_for_its_grids(self):
        _f, ours = _slot("translate-ours")
        _f2, theirs = _slot("translate-ours-resave-logic")
        from logicxkit.logic._binary import find_blocks, read_block_floats
        a = read_block_floats(ours, *find_blocks(ours)[0][::2])
        b = read_block_floats(theirs, *find_blocks(theirs)[0][::2])
        self.assertEqual(len(ours), len(theirs))
        self.assertEqual([round(v, 3) for v in a[1:7]], [-30.0, 3.06, 10.72, 115.0, 2.999, 0.083])   # written before the grids
        self.assertEqual([round(v, 3) for v in b[1:7]], [-30.0, 3.1, 10.5, 110.0, 3.0, 0.1])         # kept on Logic's grids
        self.assertEqual(a[7:], b[7:])


@_goldens.needs("sidechain-proc-bus1")
class ProC2DefaultsTest(unittest.TestCase):
    def test_the_defaults_read_and_plan(self):
        data = project_data(_goldens.path("sidechain-proc-bus1"))
        payload = channel_slots(data, owner_by_label(data, "Audio 2"))[2].raw[HEADER:]
        maps = load_maps([PACKAGED / "translate"])
        m = map_for(payload, maps)
        self.assertEqual(m.plugin, "Pro-C 2")
        s = read_settings(payload, m)
        self.assertEqual(s.values["threshold"], -18.0)
        self.assertAlmostEqual(s.values["ratio"], 4.0, places=5)
        self.assertAlmostEqual(s.values["attack"], 0.255, places=2)          # the window's "0.255 ms"
        self.assertAlmostEqual(s.values["release"], 209.2, delta=0.5)        # the window's "209.2 ms", between samples
        self.assertEqual((s.values["auto_release"], s.values["auto_gain"], s.values["mix"]), (False, True, 100.0))
        p = plan(s, next(x for x in maps if x.plugin == "Compressor"))
        self.assertEqual(p.values["Threshold"], -18.0)
        self.assertAlmostEqual(p.values["Ratio"], 3.9, places=4)             # the ratio knob has 3.9 and 4.1, no 4.0
        self.assertIn("auto_gain on: no analogue in Compressor", "\n".join(p.notes))


@_goldens.needs("translate-proq", "translate-proq-ours", "translate-proq-ours-resave-logic")
class DialledProQ4Test(unittest.TestCase):
    """A Pro-Q 4 dialled to nine bands in Logic reads what its window showed; carried into a
    Channel EQ, Logic showed the bands as planned and kept them but for its own knob positions."""

    def test_the_dialled_pro_q_4_reads_what_its_window_showed(self):
        facts, payload = _slot("translate-proq")
        maps = load_maps([PACKAGED / "translate"])
        bands = read_settings(payload, map_for(payload, maps)).bands
        self.assertEqual(len(bands), 9)
        for number, want in facts["shown"].items():
            band = bands[int(number) - 1]
            with self.subTest(number):
                self.assertEqual(band.shape.replace("_", " "), want["shape"].lower())
                freq = float(want["frequency"].split()[0])
                self.assertAlmostEqual(band.frequency, freq, delta=freq * 0.001)
                self.assertAlmostEqual(band.gain, float(want["gain"].split()[0]), delta=0.01)
                self.assertAlmostEqual(band.q, float(want["q"]), delta=0.02)      # between the curve's samples
                if band.shape in ("low_cut", "high_cut"):
                    self.assertEqual(band.slope, float(want["slope"].split()[0]))

    def test_the_plan_is_what_logic_showed_but_for_its_knobs(self):
        _f, payload = _slot("translate-proq")
        maps = load_maps([PACKAGED / "translate"])
        p = plan(read_settings(payload, map_for(payload, maps)), next(m for m in maps if m.plugin == "Channel EQ"))
        shown = _goldens.entry("translate-proq-ours-resave-logic")["facts"]["shown"]
        for name, value in p.values.items():
            with self.subTest(name):
                if name.endswith("On/Off"):
                    self.assertEqual({"On": "1", "Off": "0"}[value], shown[name])
                    continue
                got = float(re.match(r"[-+]?\d+(?:\.\d+)?", shown[name]).group())
                self.assertAlmostEqual(value, got, places=3)                       # the snap puts Q 2.43 on the knob's 2.50, 250.01 Hz on 250
        self.assertIn("band 7 notch 60 Hz Q 1.00: no analogue in Channel EQ", p.notes)
        self.assertIn("band 6 bell 4.00 kHz +2.0 dB Q 1.00: no slot of that shape in Channel EQ", p.notes)

    def test_logic_kept_our_write_but_for_its_knobs(self):
        _f, ours = _slot("translate-proq-ours")
        _f2, theirs = _slot("translate-proq-ours-resave-logic")
        from logicxkit.logic._binary import find_blocks, read_block_floats
        a = list(read_block_floats(ours, *find_blocks(ours)[0][::2]))
        b = list(read_block_floats(theirs, *find_blocks(theirs)[0][::2]))
        self.assertEqual((len(ours), len(a)), (len(theirs), len(b)))
        snapped = {10: (250.01, 250.0), 12: (2.43, 2.5), 14: (500.01, 500.0), 22: (1999.97, 2000.0),
                   26: (7999.62, 8000.0), 30: (15999.0, 16000.0)}                  # frequencies and a Q, to the knobs
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            with self.subTest(i):
                if i in snapped:
                    self.assertAlmostEqual(x, snapped[i][0], places=2)
                    self.assertAlmostEqual(y, snapped[i][1], places=2)
                else:
                    self.assertEqual(x, y)


if __name__ == "__main__":
    unittest.main()
