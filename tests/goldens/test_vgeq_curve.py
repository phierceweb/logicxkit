"""The Vintage Graphic EQ's bands show a dB value that is not linear in the word: Logic's own
saves of the 8.0K band at thirteen slider positions (`instrument-params-vintage-graphic-eq-curve*`,
`-curveb*`) make the (word, shown) points the table carries; a read of each save interpolates to
what the Controls view showed. Words written by `--set` are checked against it, not folded into
it (`test_vgeq_curve_write.py`)."""

import unittest

import _goldens
from _instparams import _block, _payload
from logicxkit.logic.services.mixer.plugin_params import decode_payload, load_tables, table_for
from logicxkit.logicx import project_data

BASE = "instrument-params-vintage-graphic-eq-curve-base"
DEFAULTS = "instrument-params-vintage-graphic-eq-defaults"
SAVES = tuple(f"instrument-params-vintage-graphic-eq-curve{k}" for k in range(4)) + tuple(f"instrument-params-vintage-graphic-eq-curveb{k}" for k in range(8))


@_goldens.needs(BASE, DEFAULTS, "instrument-set-vgeq-mine", "instrument-set-vgeq-resave-logic", *SAVES)
class CurveTest(unittest.TestCase):
    def test_each_save_reads_back_to_the_db_logic_showed(self):
        tables = load_tables()
        for key in SAVES:
            with self.subTest(key):
                payload = _payload(project_data(_goldens.path(key)), "Inst 1", DEFAULTS)
                head = _block(project_data(_goldens.path(key)), "Inst 1", DEFAULTS)
                table = table_for(tables, head[0], head[1])
                shown = float(_goldens.fact(key, "shown").split()[0])
                self.assertAlmostEqual(decode_payload(table, payload)["8.0K"], shown, places=2)

    def test_a_copy_written_at_scale_half_reads_as_logic_showed_it(self):
        """`instrument-set-vgeq-mine` holds its `words` (the typed `set` at scale 0.5, not through
        the curve); Logic's re-save kept them and its Controls view showed `shown`. Every row
        reads as shown, within the display's rounding."""
        shown = _goldens.fact("instrument-set-vgeq-resave-logic", "shown")
        for key in ("instrument-set-vgeq-mine", "instrument-set-vgeq-resave-logic"):
            payload = _payload(project_data(_goldens.path(key)), "Inst 1", DEFAULTS)
            head = _block(project_data(_goldens.path(key)), "Inst 1", DEFAULTS)
            table = table_for(load_tables(), head[0], head[1])
            decoded = decode_payload(table, payload)
            for name, word in _goldens.fact(key, "words").items():
                with self.subTest(f"{key} {name}"):
                    self.assertEqual(head[2][table.param(name).index], word)
                    self.assertAlmostEqual(decoded[name], float(shown[name].split()[0]), delta=0.05)

    def test_the_curve_is_monotone_and_its_ends_are_the_range(self):
        table = next(t for t in load_tables().values() if t.name == "Vintage Graphic EQ")
        p = table.param("8.0K")
        words, shown = [w for w, _v in p.curve], [v for _w, v in p.curve]
        self.assertEqual(words, sorted(words))
        self.assertEqual(shown, sorted(shown))
        self.assertEqual((p.min, p.max), (min(shown), max(shown)))

    def test_every_band_carries_the_curve_and_no_scale(self):
        table = next(t for t in load_tables().values() if t.name == "Vintage Graphic EQ")
        bands = [p for p in table.params if p.name in ("8.0K", "4.0K", "2.0K", "1.0K", "500", "250", "125", "63", "31")]
        self.assertEqual(len(bands), 9)
        for p in bands:
            self.assertTrue(p.curve, p.name)
            self.assertEqual(p.scale, 1.0)
        self.assertEqual(len(bands[0].curve), len(SAVES) + 1)          # the slider saves and the default's 0 dB


if __name__ == "__main__":
    unittest.main()
