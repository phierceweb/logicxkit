"""Rows an effect shows on a stereo audio strip alone (`stereofx-<slug>-base` and `-row`: the effect
on gone-i2's stereo Audio 4, one row moved): the one block word the row's save moves is the table's
word for it, and the table reads both saves as the Controls view showed them."""

import unittest

import _goldens
from logicxkit.logic._binary import find_blocks, read_block_floats
from logicxkit.logic.services.mixer.plugin_params import decode_payload, load_tables, set_by_name
from logicxkit.logic.services.mixer.plugins import slot_payloads
from logicxkit.logicx import project_data

SLUGS = ("chorus", "modulation-delay", "scanner-vibrato")
KEYS = tuple(f"stereofx-{s}-{side}" for s in SLUGS for side in ("base", "row"))


def _payload(key: str) -> bytes:
    name = _goldens.fact(key, "plugin")
    return next(p for ref, p in slot_payloads(project_data(_goldens.path(key))) if ref.channel == "Audio 4" and ref.name == name)


def _words(payload: bytes) -> list[float]:
    idx, _t, n = max(find_blocks(payload), key=lambda b: b[2])
    return list(read_block_floats(payload, idx, n))


@_goldens.needs(*KEYS)
class StereoRowsTest(unittest.TestCase):
    def setUp(self):
        self.tables = {t.name: t for t in load_tables().values()}

    def test_the_row_moves_one_word_and_the_table_names_it(self):
        for slug in SLUGS:
            base, row = f"stereofx-{slug}-base", f"stereofx-{slug}-row"
            with self.subTest(slug):
                a, b = _words(_payload(base)), _words(_payload(row))
                moved = [j for j in range(min(len(a), len(b))) if a[j] != b[j]]
                self.assertEqual(moved, [_goldens.fact(row, "word")])
                p = self.tables[_goldens.fact(row, "plugin")].param(_goldens.fact(row, "row"))
                self.assertEqual((p.index, p.evidence), (moved[0], "row"))

    def test_a_d_mode_reads_and_writes_as_its_display(self):
        """D-Mode is a checkbox over a word of 0 and 100: it reads Off and On, and On is written as 100."""
        for slug in ("chorus", "modulation-delay"):
            with self.subTest(slug):
                table = self.tables[_goldens.fact(f"stereofx-{slug}-row", "plugin")]
                self.assertEqual(decode_payload(table, _payload(f"stereofx-{slug}-base"))["D-Mode"], "Off")
                self.assertEqual(decode_payload(table, _payload(f"stereofx-{slug}-row"))["D-Mode"], "On")
                written = set_by_name(table, _payload(f"stereofx-{slug}-base"), {"D-Mode": "On"})
                self.assertEqual(_words(written), _words(_payload(f"stereofx-{slug}-row")))



@_goldens.needs("stereofx-scanner-vibrato-base", "stereofx-scanner-vibrato-row")
class StereoPhaseTest(unittest.TestCase):
    """Scanner Vibrato's Stereo Phase, a slider the mono strip never shows: Free at its low end
    (word -10), degrees to 360 at its high end, the ends read on the stereo strip."""

    def test_free_reads_and_writes_by_name_and_the_range_is_the_sliders(self):
        table = next(t for t in load_tables().values() if t.name == "Scanner Vibrato")
        p = table.param("Stereo Phase")
        self.assertEqual(decode_payload(table, _payload("stereofx-scanner-vibrato-base"))["Stereo Phase"], "Free")
        self.assertEqual(decode_payload(table, _payload("stereofx-scanner-vibrato-row"))["Stereo Phase"], 0.0)
        self.assertEqual((p.min, p.max), (-10.0, 360.0))
        self.assertEqual(_goldens.fact("stereofx-scanner-vibrato-base", "slider_ends")["Stereo Phase"], ["Free", "360"])
        written = set_by_name(table, _payload("stereofx-scanner-vibrato-row"), {"Stereo Phase": "Free"})
        self.assertEqual(_words(written)[5], -10.0)
        with self.assertRaisesRegex(ValueError, "outside"):
            set_by_name(table, _payload("stereofx-scanner-vibrato-row"), {"Stereo Phase": 400})


if __name__ == "__main__":
    unittest.main()
