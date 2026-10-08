"""The Vintage Graphic EQ curve against words written by `--set`. `instrument-set-vgeq2-mine`
holds 8.0K as word 7.5 and 500 as -10.0; `instrument-set-vgeq3-mine` holds 8.0K=5, 2.0K=1 and
500=-4.5 dialled through the thirteen-point curve (words 6.5, 1.5385, -6.9091). Logic 12.4
opened each, moved every word onto its slider position (one unit is word 0.2), showed `shown`
and re-saved it. The curve holds the 8.0K band's slider series alone, so these words are held
out: no knot is one of them, and the curve reads each within one display step (0.1 dB) of what
Logic showed — 2.0K's 1.6 reads 1.04 where Logic showed 1.1."""

import unittest

import _goldens
from logicxkit.logic._binary import find_blocks, read_block_floats
from logicxkit.logic.services.mixer.plugin_params import _along, load_tables
from logicxkit.logic.services.mixer.plugins import slot_payloads
from logicxkit.logicx import project_data

SERIES = ("vgeq2", "vgeq3")
KEYS = tuple(f"instrument-set-{s}-{side}" for s in SERIES for side in ("mine", "resave-logic"))


def _words(key: str) -> dict[str, float]:
    payload = next(p for ref, p in slot_payloads(project_data(_goldens.path(key))) if ref.channel == "Inst 1" and ref.name == "Vintage Graphic EQ")
    idx, _t, n = find_blocks(payload)[0]
    floats = read_block_floats(payload, idx, n)
    table = next(t for t in load_tables().values() if t.name == "Vintage Graphic EQ")
    return {name: floats[table.param(name).index] for name in _goldens.fact(key, "words")}


@_goldens.needs(*KEYS)
class CurveWriteTest(unittest.TestCase):
    def setUp(self):
        self.table = next(t for t in load_tables().values() if t.name == "Vintage Graphic EQ")

    def test_logic_moved_each_written_word_onto_a_slider_position(self):
        for s in SERIES:
            mine, logic = _words(f"instrument-set-{s}-mine"), _words(f"instrument-set-{s}-resave-logic")
            for name, word in _goldens.fact(f"instrument-set-{s}-mine", "words").items():
                with self.subTest(f"{s} {name}"):
                    self.assertAlmostEqual(mine[name], word, places=3)
                    moved = _goldens.fact(f"instrument-set-{s}-resave-logic", "words_logic")[name]
                    self.assertAlmostEqual(logic[name], moved, places=5)
                    self.assertAlmostEqual(moved / 0.2, round(moved / 0.2), places=4)

    def test_the_written_words_are_the_curves_inverse_of_what_was_set(self):
        for name, value in _goldens.fact("instrument-set-vgeq3-mine", "set").items():
            with self.subTest(name):
                self.assertAlmostEqual(_along(self.table.param(name).curve, value, inverse=True),
                                       _words("instrument-set-vgeq3-mine")[name], places=3)

    def test_the_curve_reads_the_held_out_words_within_a_display_step(self):
        knots = {round(w, 5) for w, _v in self.table.param("8.0K").curve}
        for s in SERIES:
            key = f"instrument-set-{s}-resave-logic"
            logic, shown = _words(key), _goldens.fact(key, "shown")
            for name, word in logic.items():
                with self.subTest(f"{s} {name}"):
                    if name == "8.0K":
                        self.assertNotIn(round(word, 5), knots)
                    self.assertAlmostEqual(_along(self.table.param(name).curve, word), float(shown[name].split()[0]), delta=0.1)


if __name__ == "__main__":
    unittest.main()
