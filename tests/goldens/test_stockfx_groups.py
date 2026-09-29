"""Every stock plug-in group as measured (`stockfx-<group>-defaults` and `-spots` in the public
manifest): each plug-in has a packaged donor, each measured one a table that reads both saves
back to the values Logic showed, and only the moved parameters' floats changed. A plug-in is
its block type and variant base together (Tape Delay and Echo share type 147). Skips without
the public corpus."""

import unittest

import _goldens
from logicxkit.logic._binary import find_blocks, read_block_floats
from logicxkit.logic._edit import owner_by_label
from logicxkit.logic.services.insert import HEADER, plugin_variant
from logicxkit.logic.services.plugin_library import load_library
from logicxkit.logic.services.plugin_params import decode, load_tables, table_for
from logicxkit.logic.services.transplant import channel_slots
from logicxkit.logicx import project_data
from logicxkit.utils.data import PACKAGED

RUNS = tuple((k, k[:-len("-defaults")] + "-spots") for k in sorted(_goldens.manifest())
             if k.startswith("stockfx-") and k.endswith("-defaults") and k[:-len("-defaults")] + "-spots" in _goldens.manifest())
SHORT = {"AdLimit": "Adaptive Limiter", "Multipr": "Multipressor", "Linear EQ": "Linear Phase EQ",
         "Single EQ": "Single Band EQ", "Cnsl EQ": "Vintage Console EQ", "Graph EQ": "Vintage Graphic EQ",
         "Tube EQ": "Vintage Tube EQ", "Tru-Tape": "Tru-Tape Delay", "Delay D": "Delay Designer",
         "Space D": "Space Designer", "St-Delay": "Stereo Delay", "QRS": "Quantec Room Simulator",
         "SmpleDly": "Sample Delay", "McrPhas": "Microphaser", "ModDel": "Modulation Delay",
         "Ringshift": "Ringshifter", "ScanVib": "Scanner Vibrato", "ClipDist": "Clip Distortion",
         "Dist II": "Distortion II", "PhaseDist": "Phase Distortion", "EVOC FB": "EVOC 20 Filterbank",
         "SpecGate": "Spectral Gate", "Rotor": "Rotor Cabinet", "Amp": "Amp Designer",
         "Bass Amp": "Bass Amp Designer", "PitchCor": "Pitch Correction", "PShft": "Pitch Shifter",
         "VocalTrf": "Vocal Transformer", "DirMix": "Direction Mixer", "Spread": "Stereo Spread",
         "BPM": "BPM Counter", "Correlatio": "Correlation Meter", "Level Mtr": "Level Meter",
         "Loudness": "Loudness Meter", "TestOsc": "Test Oscillator", "Beat Break": "Beat Breaker",
         "Binaural": "Binaural Post-Processing"}


def _blocks(data: bytes, label: str) -> list[tuple[int, list[float], int | None]]:
    """Logic's own plug-ins on the strip, in slot order, as (type, floats, variant base); a
    third-party slot (no float block) is not one of the group."""
    out = []
    for r in channel_slots(data, owner_by_label(data, label)):
        payload = r.raw[HEADER:]
        blocks = find_blocks(payload)
        if not blocks:
            continue
        idx, type_id, n = blocks[0]
        out.append((type_id, list(read_block_floats(payload, idx, n)), plugin_variant(payload)))
    return out


def _close(a, b) -> bool:
    return isinstance(a, (int, float)) and isinstance(b, (int, float)) and abs(a - b) <= max(0.011, abs(b) * 0.002)


@_goldens.needs(*(k for run in RUNS for k in run))
class StockGroupsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tables = load_tables([PACKAGED / "logic"])
        cls.donors = {(d.type_id, plugin_variant(d.raw[HEADER:]))
                      for d in load_library([PACKAGED / "donors"]) if d.kind == "native"}

    def _run(self, defaults: str, spots: str):
        types = _goldens.entry(defaults)["facts"]["types"]
        moved = {SHORT.get(k, k): v for k, v in _goldens.entry(spots)["facts"]["moved"].items()}
        label = _goldens.entry(defaults)["facts"]["channel"]
        before = dict(zip(types, _blocks(project_data(_goldens.path(defaults)), label), strict=True))
        after = dict(zip(types, _blocks(project_data(_goldens.path(spots)), label), strict=True))
        return types, moved, before, after

    def _table(self, before, name):
        return table_for(self.tables, before[name][0], before[name][2])

    def test_there_are_groups(self):
        self.assertTrue(RUNS)

    def test_every_plug_in_has_a_packaged_donor_and_every_measured_one_a_table(self):
        for defaults, spots in RUNS:
            types, moved, before, _a = self._run(defaults, spots)
            for name, type_id in types.items():
                with self.subTest(f"{defaults} {name}"):
                    self.assertEqual(before[name][0], type_id)
                    self.assertIn((type_id, before[name][2]), self.donors)
                    if name in moved:
                        table = self._table(before, name)
                        self.assertIsNotNone(table, f"no table for {name} (type {type_id}, variant {before[name][2]})")
                        self.assertEqual(table.name, name)

    def test_the_tables_read_both_saves_back_to_what_logic_showed(self):
        for defaults, spots in RUNS:
            types, moved, before, after = self._run(defaults, spots)
            for name in moved:
                table = self._table(before, name)
                by_value = {p.name for p in table.params if getattr(p, "evidence", "value") == "value"}
                for param, values in moved[name].items():
                    if param not in by_value:          # matched by order: the float is not the display
                        continue
                    with self.subTest(f"{spots} {name} {param}"):
                        d0, d1 = decode(table, before[name][1]), decode(table, after[name][1])
                        for got, want in ((d0[param], values["before"]), (d1[param], values["after"])):
                            got = {"Off": 0.0, "On": 1.0}.get(got, got)
                            self.assertTrue(_close(got, want), f"{param}: {got!r} vs {want!r}")

    def test_every_moved_parameter_changed_and_no_unmoved_one_did(self):
        """Floats the table does not name may change too (a synced time re-expressed, a
        parameter left unmapped as ambiguous); a named one changes only when its row was moved."""
        for defaults, spots in RUNS:
            types, moved, before, after = self._run(defaults, spots)
            for name in moved:
                with self.subTest(f"{spots} {name}"):
                    changed = {i for i, (a, b) in enumerate(zip(before[name][1], after[name][1], strict=True)) if a != b}
                    params = self._table(before, name).params
                    self.assertTrue({p.index for p in params if p.name in moved[name]} <= changed)
                    self.assertFalse({p.index for p in params if p.name not in moved[name]} & changed)


if __name__ == "__main__":
    unittest.main()
