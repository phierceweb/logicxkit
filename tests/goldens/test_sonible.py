"""sonible smart:comp 2 and smart:gate read through their maps from Logic's own save after every
slider moved (`sonible-*`, 2026-09-22): the values each window showed, and plans for Logic's
Compressor and Noise Gate with what does not cross reported. Skips without the public corpus."""

import unittest

import _goldens
from logicxkit.logic.services.plugins import slot_payloads
from logicxkit.logic.services.translate import load_maps, map_for, plan, read_settings
from logicxkit.logicx import project_data
from logicxkit.utils.data import PACKAGED


def _payloads(key: str) -> dict[str, bytes]:
    data = project_data(_goldens.path(key))
    maps = load_maps([PACKAGED / "translate"])
    out = {}
    for ref, payload in slot_payloads(data):
        m = map_for(payload, maps)
        if m is not None and m.component and ref.channel == _goldens.entry(key)["facts"]["channel"]:
            out[m.plugin] = payload
    return out


@_goldens.needs("sonible-defaults", "sonible-spots", "sonible-mono")
class SonibleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.maps = load_maps([PACKAGED / "translate"])
        cls.spots = _payloads("sonible-spots")

    def test_both_read_what_their_windows_showed(self):
        shown = _goldens.entry("sonible-spots")["facts"]["shown"]
        for plugin, want in shown.items():
            s = read_settings(self.spots[plugin], map_for(self.spots[plugin], self.maps))
            for name, value in want.items():
                with self.subTest(f"{plugin} {name}"):
                    got = s.values[name]
                    self.assertEqual(got, value) if isinstance(value, bool) else self.assertAlmostEqual(got, value, delta=0.01)

    def test_smart_comp_2_into_the_compressor(self):
        p = plan(read_settings(self.spots["smart:comp 2"], map_for(self.spots["smart:comp 2"], self.maps)),
                 next(m for m in self.maps if m.plugin == "Compressor"))
        self.assertEqual(p.values["Threshold"], -10.0)                        # -10.2 dB on the 0.5 dB grid
        self.assertEqual((p.values["Ratio"], p.values["Attack"], p.values["Release"]), (1.5, 41.0, 390.0))   # 1.45 stored, half up; the knobs' positions Logic showed
        self.assertEqual((p.values["Make Up"], p.values["Mix"], p.values["Input Gain"]), (2.5, 95.0, 2.5))
        self.assertEqual(p.values["Knee"], 0.0)                               # 0.3 dB / 72 on the 0.1 grid
        notes = "\n".join(p.notes)
        self.assertIn("auto_gain on: no analogue in Compressor", notes)
        self.assertIn("smart:comp 2 stage 2:", notes)

    def test_smart_gate_into_the_noise_gate(self):
        p = plan(read_settings(self.spots["smart:gate"], map_for(self.spots["smart:gate"], self.maps)),
                 next(m for m in self.maps if m.plugin == "Noise Gate"))
        self.assertEqual((p.values["Attack"], p.values["Release"], p.values["Hold"]), (16.0, 351.0, 10.0))   # the release knob's position, shown 351.0
        self.assertNotIn("Threshold", p.values)
        self.assertIn("smart:gate Threshold: smart:gate's threshold is a percentage", "\n".join(p.notes))

    @_goldens.needs("translate-sonible-ours", "translate-sonible-resave-logic")
    def test_logic_kept_the_translations_on_its_knobs(self):
        """Our Compressor and Noise Gate read back as planned; Logic's re-save keeps every value
        on a grid and settles the knobs' own positions for attack, hold and release."""
        from logicxkit.logic._binary import find_blocks, read_block_floats
        from logicxkit.logic._edit import owner_by_label
        from logicxkit.logic.services.stream import HEADER
        from logicxkit.logic.services.transplant import channel_slots
        rows = {}
        for key in ("translate-sonible-ours", "translate-sonible-resave-logic"):
            data = project_data(_goldens.path(key))
            slots = channel_slots(data, owner_by_label(data, "Audio 2"))
            rows[key] = [read_block_floats(r.raw[HEADER:], *find_blocks(r.raw[HEADER:])[0][::2]) for r in slots[:2]]
        ours, theirs = rows["translate-sonible-ours"], rows["translate-sonible-resave-logic"]
        comp = [round(v, 3) for v in ours[0][1:7]]
        self.assertEqual(comp, [-10.0, 1.5, 40.0, 400.0, 2.5, 0.0])
        self.assertEqual([round(v, 3) for v in theirs[0][1:7]], [-10.0, 1.5, 41.0, 390.0, 2.5, 0.0])
        self.assertEqual([round(v, 3) for v in ours[1][4:7]], [16.0, 10.0, 350.0])       # gate attack, hold, release
        self.assertEqual([round(v, 1) for v in theirs[1][4:7]], [16.0, 10.0, 351.0])   # 350.99 stored, shown 351.0
        shown = _goldens.entry("translate-sonible-resave-logic")["facts"]["shown"]
        self.assertEqual((shown["Compressor"]["Attack"], shown["Noise Gate"]["Release"]), ("41.0 ms", "351.0 ms"))

    def test_the_defaults_and_the_mono_instances_read_too(self):
        for key in ("sonible-defaults", "sonible-mono"):
            with self.subTest(key):
                for plugin, payload in _payloads(key).items():
                    s = read_settings(payload, map_for(payload, self.maps))
                    self.assertTrue(s.values, plugin)


if __name__ == "__main__":
    unittest.main()
