"""Settings carried between plug-ins of one family through the vocabulary: the maps'
conversions both ways, a slot read through its map, and a plan for a target with its report."""

import plistlib
import struct
import unittest

from logicxkit.au.services.izotope import pack_izotope
from logicxkit.logic.services.translate.translate import Item, Map, Settings, load_maps, map_for, maps_for, plan, read_settings
from logicxkit.utils.data import PACKAGED

MAPS = load_maps([PACKAGED / "translate"])
PROC = next(m for m in MAPS if m.plugin == "Pro-C 2")
COMP = next(m for m in MAPS if m.plugin == "Compressor")
NEUTRON = [m for m in MAPS if m.plugin == "Neutron 5"]


def au_payload(values: dict[int, float], count: int = 46, subtype: str = "FC2p") -> bytes:
    """A third-party slot payload: a prefix, then the AU ClassInfo plist with id/value pairs."""
    blob = bytearray(12 + 8 * count)
    struct.pack_into(">I", blob, 8, count)
    for i in range(count):
        struct.pack_into(">If", blob, 12 + 8 * i, i, values.get(i, 0.0))
    code = lambda s: int.from_bytes(s.encode(), "big")          # noqa: E731  OSType numbers, as Logic writes them
    plist = plistlib.dumps({"type": code("aumf"), "subtype": code(subtype), "manufacturer": code("FabF"), "version": 1,
                            "name": "Default Setting", "data": bytes(blob)}, fmt=plistlib.FMT_XML)
    return bytes(180) + plist


def izotope_payload(**modules: dict) -> bytes:
    """A Neutron 5 slot payload: the AU ClassInfo plist whose data is the zlib JSON state."""
    kind = lambda v: "Bool" if isinstance(v, bool) else "Float" if isinstance(v, float) else "UInt"   # noqa: E731
    doc = {"DSP State": {"Type": "Dictionary", "Value": {"DSP Elements": {"Type": "Dictionary", "Value": {
        name: {"Type": "Dictionary", "Value": {k: {"Type": kind(v), "Value": v} for k, v in params.items()}}
        for name, params in modules.items()}}}}}
    code = lambda s: int.from_bytes(s.encode(), "big")          # noqa: E731
    plist = plistlib.dumps({"type": code("aufx"), "subtype": code("ZNN5"), "manufacturer": code("iZtp"), "version": 1,
                            "name": "Default Setting", "data": pack_izotope(doc)}, fmt=plistlib.FMT_XML)
    return bytes(180) + plist


def native_payload(floats: list[float], type_id: int = 154) -> bytes:
    p = bytearray(184 + 12 + 4 * len(floats))
    p[184:192] = b"GAMETSPP"
    struct.pack_into("<III", p, 172, 24 + len(floats) * 4, 1, len(floats))
    struct.pack_into("<I", p, 192, type_id)
    struct.pack_into(f"<{len(floats)}f", p, 196, *floats)                 # the floats follow the type word
    return bytes(p)


class LoadTest(unittest.TestCase):
    def test_no_map_directory_anywhere_is_an_error_not_an_empty_list(self):
        from unittest import mock

        from logicxkit.logic.services.translate import translate
        from logicxkit.utils.data import MissingData
        with mock.patch.object(translate, "data_dirs", return_value=[]):
            with self.assertRaises(MissingData):
                translate.load_maps()
        self.assertEqual(translate.load_maps([]), [])


class ItemTest(unittest.TestCase):
    def test_a_curve_reads_both_ways(self):
        ratio = PROC.items["ratio"]
        self.assertAlmostEqual(ratio.to_vocab(0.6), 4.0, places=6)
        self.assertAlmostEqual(ratio.to_stored(4.0), 0.6, places=6)
        self.assertAlmostEqual(ratio.to_vocab(0.6125), 4.25, places=6)      # between two samples
        self.assertAlmostEqual(PROC.items["attack"].to_vocab(0.4), 16.0)
        self.assertAlmostEqual(PROC.items["release"].to_stored(198.2), 0.4, places=6)

    def test_a_scale_a_floor_and_a_switch(self):
        gain = PROC.items["make_up"]
        self.assertAlmostEqual(gain.to_vocab(-0.2), -7.2)
        self.assertIsNone(gain.to_vocab(-1.0))                                # silent
        self.assertAlmostEqual(gain.to_stored(3.6), 0.1)
        self.assertEqual(PROC.items["auto_release"].to_vocab(1.0), True)
        self.assertEqual(COMP.items["auto_release"].to_stored(True), 1.0)
        self.assertAlmostEqual(COMP.items["knee"].to_vocab(0.25), 18.0)      # approximate, dB/72


class SnapTest(unittest.TestCase):
    """A native write lands on a sampled slider position, and stays put between them."""

    def test_a_sampled_position_is_taken_and_a_gap_lands_on_the_curves_unit(self):
        from logicxkit.logic.services.mixer.slider import snap
        m = Map("compressor", "Synthetic", {}, type=999,
                raw={"automation": {"Ratio": {"per": 128, "units": [[0, 1.0], [10, 1.5], [20, 2.0], [40, 4.0], [85, 30.0]]}}})
        self.assertEqual(snap(m, "Ratio", 2.02), 2.0)                       # unit 20, sampled (units follow the log of a ratio)
        gap = 3.0314                                                        # unit 32, not sampled: 2 * 2 ** (12 / 20)
        self.assertEqual(snap(m, "Ratio", 3.0), gap)
        self.assertEqual(snap(m, "Ratio", 1.49), 1.5)
        self.assertEqual(snap(m, "Threshold", -20.3), -20.3)                # unmeasured: as is
        from logicxkit.logic.services.translate.translate_write import _on_slider
        item = Item("Ratio")
        self.assertEqual(_on_slider(m, item, 3.0), (gap, "between Synthetic's sampled Ratio positions; written on the curve's nearest unit"))
        self.assertEqual(_on_slider(m, item, 2.02), (2.0, None))
        self.assertEqual(_on_slider(m, item, 40.0), (30.0, "Synthetic's Ratio slider runs 1..30; set to 30"))


class ReadTest(unittest.TestCase):
    def test_a_third_party_slot_reads_through_its_map(self):
        payload = au_payload({1: -18.0, 2: 0.6, 3: 18.0, 5: 0.4, 6: 0.4, 7: 1.0, 10: -1.0, 14: 1.0, 34: 1.0, 35: 0.0, 37: 0.0})
        self.assertIs(map_for(payload, MAPS), PROC)
        s = read_settings(payload, PROC)
        self.assertEqual(s.values["threshold"], -18.0)
        self.assertAlmostEqual(s.values["ratio"], 4.0, places=6)
        self.assertAlmostEqual(s.values["attack"], 16.0, places=4)
        self.assertAlmostEqual(s.values["release"], 198.2, places=3)
        self.assertEqual((s.values["auto_release"], s.values["auto_gain"], s.values["mix"]), (True, True, 100.0))
        self.assertEqual(s.silent, ["make_up"])

    def test_a_native_slot_reads_through_its_table(self):
        floats = [0.0, -20.0, 2.1, 15.0, 51.0, 0.0, 0.7] + [0.0] * 22
        floats[25], floats[27], floats[28] = 100.0, 0.0, 0.0
        payload = native_payload(floats)
        self.assertIs(map_for(payload, MAPS), COMP)
        s = read_settings(payload, COMP)
        for name, want in (("threshold", -20.0), ("ratio", 2.1), ("attack", 15.0), ("release", 51.0)):
            self.assertAlmostEqual(s.values[name], want, places=4)         # float32 on the way in
        self.assertAlmostEqual(s.values["knee"], 0.7 * 72, places=3)
        self.assertEqual(s.values["mix"], 100.0)

    def test_no_map_for_an_unknown_plug_in(self):
        self.assertIsNone(map_for(native_payload([0.0] * 5, type_id=9999), MAPS))


class PlanTest(unittest.TestCase):
    def test_pro_c_2_into_the_compressor(self):
        payload = au_payload({1: -18.0, 2: 0.6, 3: 18.0, 5: 0.4, 6: 0.4, 7: 0.0, 8: 5.0, 10: 0.1, 14: 1.0, 34: 1.5, 35: 0.0, 37: -0.1})
        p = plan(read_settings(payload, PROC), COMP)
        self.assertEqual(p.values["Threshold"], -18.0)
        self.assertAlmostEqual(p.values["Ratio"], 3.9, places=4)             # the ratio slider has 3.9 and 4.1, no 4.0: down
        self.assertAlmostEqual(p.values["Attack"], 16.0, places=4)
        self.assertAlmostEqual(p.values["Release"], 190.0, places=4)         # the release knob has 190 and 210 around it
        self.assertAlmostEqual(p.values["Make Up"], 3.5, places=4)          # 3.6 dB on Logic's 0.5 dB grid
        self.assertAlmostEqual(p.values["Knee"], 0.3, places=4)             # 18/72 = 0.25 on its 0.1 grid
        self.assertEqual((p.values["Mix"], p.values["Auto Release"]), (100.0, "Off"))
        self.assertAlmostEqual(p.values["Output Gain"], -3.5, places=4)     # -3.6 dB on the 0.5 dB grid
        notes = "\n".join(p.notes)
        self.assertIn("mix 150%: Compressor's Mix stops at 100%", notes)
        self.assertIn("knee 18 dB -> Knee 0.3: approximate", notes)
        self.assertIn("lookahead 5 ms: no analogue in Compressor", notes)
        self.assertIn("auto_gain on: no analogue in Compressor", notes)

    def test_a_target_step_rounds_the_value(self):
        payload = au_payload({1: -18.0, 2: 0.525, 5: 0.35, 6: 0.3, 10: 0.0833, 34: 0.8})
        p = plan(read_settings(payload, PROC), COMP)
        self.assertEqual((p.values["Ratio"], p.values["Make Up"]), (3.1, 3.0))
        self.assertAlmostEqual(p.values["Attack"], 10.5, places=3)           # the knob's nearest position (Logic: 10.72 -> 10.5)
        self.assertAlmostEqual(p.values["Release"], 110.0, places=3)         # the curve's 115.000009 is 115, the midpoint of 110 and 120: down

    def test_what_a_source_does_not_carry_is_reported(self):
        src = Map("compressor", "Some Comp", {"threshold": Item("Threshold", id=1)}, component=("aufx", "xxxx", "Some"),
                  not_carried={"Magic": "no analogue anywhere"})
        s = read_settings(au_payload({1: -12.0}), PROC)
        s.map = src
        p = plan(s, COMP)
        self.assertIn("Some Comp Magic: no analogue anywhere", p.notes)

    def test_families_must_agree(self):
        gate = Map("gate", "Some Gate", {"threshold": Item("Threshold")}, type=179)
        with self.assertRaisesRegex(ValueError, "compressor"):
            plan(read_settings(au_payload({1: -18.0}), PROC), gate)


class NeutronTest(unittest.TestCase):
    """Neutron 5 carries three families; each map reads its element, the first not bypassed."""

    COMP = {"Bypass": False, "Band 0 Comp Threshold": -8.06, "Band 0 Comp Ratio": 2.44, "Band 0 Comp Attack": 20.5,
            "Band 0 Comp Release": 51.2, "Band 0 Comp Soft Knee": 0.0, "Band 0 Gain": 1.5, "Band 0 Mix": 90.0,
            "Global Gain": 0.0}
    GATE = {"Bypass": False, "Band 0 Gate Threshold": -40.0, "Band 0 Gate Attack": 1.0, "Band 0 Gate Hold": 0.01,
            "Band 0 Gate Release": 100.0, "Band 0 Gate Hysteresis Amount": 3.0, "Band 0 Gate Ratio": 8.0}
    EQ = {"Bypass": False, "Band 1 Enable": True, "Band 1 Frequency": 150.7, "Band 1 Gain": -1.0, "Band 1 Q": 0.56,
          "Band 1 Shape": 1, "Band 1 is static (dynamics off)": True,
          "Band 2 Enable": False, "Band 2 Frequency": 1000.0, "Band 2 Gain": 3.0, "Band 2 Q": 1.0, "Band 2 Shape": 1,
          "Band 2 is static (dynamics off)": True,
          "Band 3 Enable": True, "Band 3 Frequency": 4000.0, "Band 3 Gain": 2.0, "Band 3 Q": 1.4, "Band 3 Shape": 1,
          "Band 3 is static (dynamics off)": False}

    def payload(self, **more):
        return izotope_payload(**{"Dynamics 0": self.COMP, "Dynamics 1": {**self.COMP, "Bypass": True, "Band 0 Comp Ratio": 9.0},
                                  "Gate Expander": self.GATE, "Dynamic EQ": self.EQ, **more})

    def test_the_three_maps_by_family(self):
        found = maps_for(self.payload(), MAPS)
        self.assertEqual([m.family for m in found], ["compressor", "eq", "gate"])
        self.assertIs(map_for(self.payload(), MAPS), found[0])

    def test_the_compressor_reads_the_live_dynamics_element(self):
        s = read_settings(self.payload(), next(m for m in NEUTRON if m.family == "compressor"))
        self.assertEqual(s.values["threshold"], -8.06)
        self.assertEqual(s.values["ratio"], 2.44)                          # Dynamics 0, not the bypassed 1
        self.assertEqual((s.values["attack"], s.values["release"], s.values["mix"], s.values["make_up"]), (20.5, 51.2, 90.0, 1.5))
        self.assertEqual(s.notes, [])
        both_off = self.payload(**{"Dynamics 0": {**self.COMP, "Bypass": True}})
        s = read_settings(both_off, next(m for m in NEUTRON if m.family == "compressor"))
        self.assertEqual(s.values["ratio"], 2.44)
        self.assertEqual(s.notes, ["Neutron 5's Dynamics 0 is bypassed"])

    def test_the_gate_and_the_eq_read_their_elements(self):
        s = read_settings(self.payload(), next(m for m in NEUTRON if m.family == "gate"))
        self.assertEqual((s.values["threshold"], s.values["hold"], s.values["hysteresis"]), (-40.0, 10.0, -3.0))   # seconds to ms; Close is positive
        s = read_settings(self.payload(), next(m for m in NEUTRON if m.family == "eq"))
        self.assertEqual([(b.number, b.shape, b.frequency, b.gain, b.dynamic) for b in s.bands],
                         [(1, "bell", 150.7, -1.0, False), (3, "bell", 4000.0, 2.0, True)])      # band 2 is off; shape 1 is Bell
        self.assertEqual(s.bands[0].q, 0.56)

    def test_the_compressor_crosses_into_logics(self):
        p = plan(read_settings(self.payload(), next(m for m in NEUTRON if m.family == "compressor")), COMP)
        self.assertEqual(p.values["Threshold"], -8.0)                      # the target's 0.5 dB step
        self.assertAlmostEqual(p.values["Attack"], 20.5, delta=1.0)        # the nearest sampled slider unit
        self.assertEqual(p.values["Mix"], 90.0)

    def test_a_bypassed_element_sends_the_native_in_bypassed(self):
        """Every Dynamics element off: the settings still read from the first, and the plan
        has the native go in bypassed, saying so."""
        both_off = self.payload(**{"Dynamics 0": {**self.COMP, "Bypass": True}})
        s = read_settings(both_off, next(m for m in NEUTRON if m.family == "compressor"))
        self.assertTrue(s.bypassed)
        p = plan(s, COMP)
        self.assertTrue(p.bypass)
        self.assertIn("Neutron 5's Dynamics 0 is bypassed; Compressor goes in bypassed", p.notes)
        live = plan(read_settings(self.payload(), next(m for m in NEUTRON if m.family == "compressor")), COMP)
        self.assertFalse(live.bypass)

    def test_a_band_on_without_a_frequency_is_refused(self):
        eq = {k: v for k, v in self.EQ.items() if k != "Band 1 Frequency"}
        with self.assertRaises(ValueError) as e:
            read_settings(self.payload(**{"Dynamic EQ": eq}), next(m for m in NEUTRON if m.family == "eq"))
        self.assertIn("band 1 is on but its state has no frequency", str(e.exception))

    def test_the_state_is_read_only(self):
        from logicxkit.logic.services.translate.translate_write import write_settings
        with self.assertRaises(ValueError):
            write_settings(self.payload(), next(m for m in NEUTRON if m.family == "compressor"), {"threshold": -20.0})


class SliderMapTest(unittest.TestCase):
    """A map may carry a slider grid alone: found by type for the grid, no translation map."""
    GRID = {"plugin": "Limiter", "type": 199, "automation": {"Gain": {"per": 128, "units": [[0, -20.0], [1, -19.9]]}}}

    def test_a_map_without_a_family_loads_and_is_found_by_type(self):
        from logicxkit.logic.services.mixer.slider import slider_curve
        m = Map.from_dict(self.GRID)
        self.assertIsNone(m.family)
        self.assertEqual(maps_for(native_payload([0.0] * 13, 199), [m]), [m])
        self.assertEqual(slider_curve(m, "Gain"), ((0.0, -20.0), (1.0, -19.9)))

    def test_a_family_less_map_is_no_translation_map(self):
        m = Map.from_dict(self.GRID)
        with self.assertRaisesRegex(ValueError, "slider grid, not a translation map"):
            plan(Settings(m), m)

    def test_a_family_less_map_reads_and_writes_no_settings(self):
        from logicxkit.logic.services.translate.translate import read_settings
        from logicxkit.logic.services.translate.translate_write import write_settings
        m, payload = Map.from_dict(self.GRID), native_payload([0.0] * 13, 199)
        with self.assertRaisesRegex(ValueError, "no family; it has no settings to read"):
            read_settings(payload, m)
        with self.assertRaisesRegex(ValueError, "no family; it has no settings to write"):
            write_settings(payload, m, {"gain": 0})


class TranslationGridTest(unittest.TestCase):
    def test_a_measured_row_takes_the_sliders_unit_not_the_vocabularys_step(self):
        """swap-plugin and tracking-chains land where `--set` does: Ratio 3.03 on 3.1, not on the
        vocabulary's step, Make Up 10.3 on the curve's 10.5, Threshold -46.75 on the line's -46.5."""
        from logicxkit.logic.services.mixer.slider import grid_value
        values = {"ratio": 3.03, "make_up": 10.3, "threshold": -46.75}
        out = plan(Settings(COMP, values=values), COMP)
        self.assertEqual((out.values["Ratio"], out.values["Make Up"], out.values["Threshold"]), (3.1, 10.5, -46.5))
        for name, v in values.items():
            item = COMP.items[name]
            self.assertEqual(out.values[item.param], grid_value(COMP, item.param, item.to_stored(v))[0])

    def test_a_non_finite_source_value_is_refused_by_name(self):
        with self.assertRaisesRegex(ValueError, "ratio: inf is not a finite number"):
            plan(Settings(COMP, values={"ratio": float("inf")}), COMP)
        with self.assertRaisesRegex(ValueError, "threshold: nan is not a finite number"):   # a third-party target too
            plan(Settings(COMP, values={"threshold": float("nan")}), PROC)

    def test_the_band_planners_take_the_sliders_unit_too(self):
        """An EQ gain 1.55 lands on 1.5 in Channel EQ and Linear Phase EQ (Logic kept Channel EQ's
        1.55 as 1.5, `slider-linear-resave-logic`); a Multipressor threshold lands where `--set` does."""
        from logicxkit.logic.services.mixer.slider import grid_value
        from logicxkit.logic.services.translate.translate_eq import Band, plan_bands
        from logicxkit.logic.services.translate.translate_mb import _gridded
        band = Band("bell", 1000.0, 1.55, 1.0, True, None, False, 1)
        for name in ("Channel EQ", "Linear Phase EQ"):
            target = next(m for m in MAPS if m.plugin == name)
            values, _notes, placed = plan_bands([band], None, target, target)
            with self.subTest(name):
                self.assertEqual(values[placed[1]["gain"]], 1.5)
        q_band = Band("bell", 20.1004, 0.0, 0.1054, True, None, False, 1)   # a hair above two knob midpoints: up, as `--set` goes
        lpeq = next(m for m in MAPS if m.plugin == "Linear Phase EQ")
        values, _notes, placed = plan_bands([q_band], None, lpeq, lpeq)
        self.assertEqual((values[placed[1]["frequency"]], values[placed[1]["q"]]), (20.2, 0.11))
        from logicxkit.logic.services.translate.translate_write import _slot_values
        written = _slot_values(lpeq, Band("bell", 20.1004, 0.0, 0.1054, True, None, False, 3), [])      # `settings --set band 3=…`
        self.assertEqual((written["Peak 1 Frequency"], written["Peak 1 Q-Factor"]), (20.2, 0.11))
        from test_translate_mb import multipressor_payload
        mp = next(m for m in MAPS if m.plugin == "Multipressor")
        source = read_settings(multipressor_payload({"Band 1 Comp. Threshold": -18.0, "Band 1 Comp. Ratio": 1.9551, "Band 1 Attack": 0.2504}), mp)
        out = plan(source, mp)                                               # a hair above two knob midpoints: up, as `--set` goes
        self.assertEqual((out.values["Band 1 Comp. Ratio"], out.values["Band 1 Attack"]), (1.977, 0.5))
        row = mp.raw["slots"][0]["threshold"]
        self.assertEqual(_gridded(mp, row, -59.45, 0.5), grid_value(mp, row, -59.45)[0])
        self.assertNotEqual(_gridded(mp, row, -59.45, 0.5), -60.0)


if __name__ == "__main__":
    unittest.main()
