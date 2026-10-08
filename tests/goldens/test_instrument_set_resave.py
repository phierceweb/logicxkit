"""`--set` on the instrument tables, opened and re-saved by Logic 12.4 (`instrument-set-<slug>-mine`
and `-resave-logic`): each write kind — block floats, a millisecond word shown in seconds, an
int32 word past the block with its float mirror, floats past the block, scaled bands, a word
whose row moves another — read back in Logic's Controls view as set, and re-saved as written
but where Logic puts a value on its own slider position or derives a linked word."""

import struct
import unittest

import _goldens
from logicxkit.logic._binary import find_blocks, read_block_floats
from logicxkit.logic.services.mixer.plugin_params import decode_payload, load_tables, table_for
from logicxkit.logic.services.mixer.plugins import slot_payloads
from logicxkit.logic.services.mixer.slot_identity import slot_header
from logicxkit.logic.services.mixer.slot_width import plugin_variant
from logicxkit.logicx import project_data

SLUGS = ("es1", "esm", "b3", "es2", "vgeq")
KEYS = tuple(f"instrument-set-{s}-{side}" for s in SLUGS for side in ("mine", "resave-logic"))


def _payload(key: str) -> bytes:
    name = _goldens.fact(key, "plugin")
    return next(p for ref, p in slot_payloads(project_data(_goldens.path(key))) if ref.channel == "Inst 1" and ref.name == name)


@_goldens.needs(*KEYS)
class SetResavedTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tables = load_tables()

    def _decoded(self, key: str) -> dict:
        payload = _payload(key)
        head = slot_header(payload)
        return decode_payload(table_for(self.tables, head.code, plugin_variant(payload)), payload)

    def test_the_written_copy_decodes_to_what_was_set(self):
        """A copy whose `words` were written at another scale than its table's reads as Logic
        showed it instead (`test_vgeq_curve.py`)."""
        for slug in SLUGS:
            key = f"instrument-set-{slug}-mine"
            if _goldens.fact(key, "words") is not None:
                continue
            with self.subTest(slug):
                decoded = self._decoded(key)
                for name, value in _goldens.fact(key, "set").items():
                    self.assertAlmostEqual(float(decoded[name]), float(value), places=2, msg=name)

    def test_logic_kept_each_value_or_moved_it_onto_its_slider(self):
        """ES1's Glide 120 ms came back 124 ms: Logic puts a value between slider positions on
        one; every other word came back as written."""
        for slug in SLUGS:
            key = f"instrument-set-{slug}-resave-logic"
            if _goldens.fact(key, "words") is not None:
                continue                                       # its words held as written: `test_vgeq_curve.py`
            with self.subTest(slug):
                decoded = self._decoded(key)
                want = {**_goldens.fact(key, "set"), **_goldens.fact(key, "moved")}
                for name, value in want.items():
                    self.assertAlmostEqual(float(decoded[name]), float(value), places=2, msg=name)

    def test_logic_derived_the_linked_word_from_the_one_written(self):
        """ES2's MM2 Amount written alone: Logic's load set word 47 to the same value."""
        ours, logic = _payload("instrument-set-es2-mine"), _payload("instrument-set-es2-resave-logic")
        words = [read_block_floats(p, *find_blocks(p)[0][::2]) for p in (ours, logic)]
        self.assertEqual((words[0][46], words[0][47]), (0.5, 0.0))
        self.assertEqual((words[1][46], words[1][47]), (0.5, 0.5))
        self.assertEqual(_goldens.fact("instrument-set-es2-resave-logic", "derived"), {"47": 0.5})

    def test_the_mirror_of_a_lower_manual_drawbar_is_kept_in_step(self):
        for key in ("instrument-set-b3-mine", "instrument-set-b3-resave-logic"):
            payload = _payload(key)
            self.assertEqual((struct.unpack_from("<i", payload, 1060)[0], struct.unpack_from("<f", payload, 1220)[0]), (3, 3.0))

    def test_the_controls_view_showed_the_rows_as_set(self):
        """The displays the Controls view showed (read by `tools/driver/controls.py`), as the
        manifest records them: ES1's Glide on its slider position, the Vintage Graphic EQ's
        8.0K band 2.7 dB for a word of 4.0 — its display is not the word's half past 1 dB."""
        for slug in SLUGS:
            shown = _goldens.fact(f"instrument-set-{slug}-resave-logic", "shown")
            self.assertTrue(shown, slug)
        self.assertEqual(_goldens.fact("instrument-set-es1-resave-logic", "shown")["Glide"], "124.000 ms")
        self.assertEqual(_goldens.fact("instrument-set-vgeq-resave-logic", "shown")["8.0K"], "2.7 dB")


if __name__ == "__main__":
    unittest.main()
