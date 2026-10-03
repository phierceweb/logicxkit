"""Raw floats between slider positions, re-saved by Logic, land where `slider.snap` puts
them, and a copy written through the snap comes back as written. Skips without the public corpus."""

import unittest

import _goldens
from logicxkit.logic._edit import owner_by_label
from logicxkit.logic.services.stream.stream import HEADER
from logicxkit.logic.services.mixer.transplant import channel_slots
from logicxkit.logic.services.mixer.slider import snap
from logicxkit.logic.services.translate.translate import load_maps, map_for, read_settings
from logicxkit.logicx import project_data
from logicxkit.utils.data import PACKAGED

MAPS = load_maps([PACKAGED / "translate"])


def _slot(key: str, plugin: str):
    data = project_data(_goldens.path(key))
    facts = _goldens.entry(key)["facts"]
    payload = channel_slots(data, owner_by_label(data, facts["channel"]))[facts["slots"][plugin] - 1].raw[HEADER:]
    m = map_for(payload, MAPS)
    return m, read_settings(payload, m).values


@_goldens.needs("snap-raw", "snap-raw-resave-logic", "snap-ours", "snap-ours-resave-logic")
class SnapTest(unittest.TestCase):
    def test_logic_lays_raw_compressor_floats_where_the_snap_does(self):
        comp, raw = _slot("snap-raw", "Compressor")
        _m, kept = _slot("snap-raw-resave-logic", "Compressor")
        self.assertEqual((raw["ratio"], raw["attack"], raw["release"]), (4.0, 20.5, 115.0))
        for name, param in (("ratio", "Ratio"), ("attack", "Attack"), ("release", "Release")):
            with self.subTest(name):
                self.assertAlmostEqual(kept[name], snap(comp, param, raw[name]), places=5)
        self.assertEqual((round(kept["ratio"], 4), kept["attack"], kept["release"]), (3.9, 20.0, 110.0))

    def test_the_gate_hold_midpoint_went_up_and_its_release_to_the_positions_own_value(self):
        _m, raw = _slot("snap-raw", "Noise Gate")
        _m, kept = _slot("snap-raw-resave-logic", "Noise Gate")
        self.assertEqual((raw["hold"], raw["release"]), (205.0, 351.0))
        self.assertEqual(kept["hold"], 210.0)                                 # the snap takes this tie down
        self.assertAlmostEqual(kept["release"], 350.99, places=2)

    def test_a_snapped_write_comes_back_as_written(self):
        for plugin in ("Compressor", "Noise Gate"):
            _m, ours = _slot("snap-ours", plugin)
            _m, kept = _slot("snap-ours-resave-logic", plugin)
            for name, value in ours.items():
                with self.subTest(plugin=plugin, name=name):
                    if (plugin, name) == ("Noise Gate", "release"):
                        self.assertAlmostEqual(kept[name], value, places=1)   # 351 written, 350.99 kept
                    else:
                        self.assertEqual(kept[name], value)


class LinearRowsTest(unittest.TestCase):
    """A dB row sampled every few units (`slider.is_linear`) treats a unit between its samples as
    exact. Every value Logic wrote on such a row in the public corpus sits on a whole unit of it,
    sampled or not — Compressor Threshold alone at units 60, 61, 62, 65 and 70, none sampled."""

    def test_logic_writes_the_unsampled_units_where_the_line_puts_them(self):
        import struct

        from logicxkit.logic._binary import find_blocks
        from logicxkit.logic.services.mixer.slot_width import plugin_variant
        from logicxkit.logic.services.stream.stream import project_records
        from logicxkit.logic.services.mixer.plugin_params import decode, load_tables, table_for
        from logicxkit.logic.services.mixer.slider import along, is_linear, slider_curve
        natives, tables = {m.type: m for m in MAPS if m.type is not None}, load_tables()
        import json
        public = json.loads(_goldens.PUBLIC.read_text())
        keys = [k for k, e in public.items() if isinstance(e, dict) and str(e.get("path", "")).endswith(".logicx")
                and not e["path"][:-len(".logicx")].endswith(("-ours", "-mine", "-raw"))]
        unsampled = 0
        for key in keys:
            if (path := _goldens.path(key)) is None or not path.exists():
                continue
            for r in project_records(project_data(path)):
                p = r.raw[HEADER:]
                blocks = find_blocks(p)
                if not blocks or (m := natives.get(blocks[0][1])) is None:
                    continue
                if (t := table_for(tables, blocks[0][1], plugin_variant(p))) is None:
                    continue
                at, _type, n = blocks[0]
                values = decode(t, list(struct.unpack_from(f"<{n}f", p, at + 12)))
                for param in m.raw.get("automation", {}):
                    curve = slider_curve(m, param)
                    if not curve or not is_linear(curve) or not isinstance(values.get(param), float):
                        continue
                    unit = along(curve, values[param], inverse=True)
                    if curve[0][0] <= unit <= curve[-1][0]:
                        with self.subTest(key=key, param=param, value=values[param]):
                            self.assertAlmostEqual(unit, round(unit), delta=1e-3)
                        unsampled += round(unit) not in {u for u, _v in curve}
        self.assertGreater(unsampled, 100)


if __name__ == "__main__":
    unittest.main()
