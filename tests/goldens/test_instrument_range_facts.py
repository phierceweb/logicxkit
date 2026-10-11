"""Each table range is consistent with the staged read it came from: the defaults save's
`slider_ends` fact holds what the Controls view showed with the slider at each end, and the
table's `min` and `max` are those displays' numbers in the parameter's unit. A save holding one
plug-in keys the fact by parameter name; a group save (`stockfx-<group>-defaults-12-4`) by plug-in
name first, and every plug-in named must have a table. The save itself holds each ranged row's
default in the row's word, so a range on another row's word or in another unit fails."""

import re
import unittest

import _goldens
from logicxkit.logic.services.mixer.plugin_params import decode_payload, load_tables, table_of
from logicxkit.logic.services.mixer.plugins import slot_payloads
from logicxkit.logicx import project_data

KEYS = tuple(k for k in sorted(_goldens.manifest())
             if re.search(r"-defaults(-12-4)?$", k) and _goldens.fact(k, "slider_ends"))


def _number(text: str, unit: str) -> float | None:
    """The display's number in the parameter's unit (s and kHz over ms and Hz words a thousandfold)."""
    m = re.search(r"-?\d+(?:\.\d+)?", (text or "").replace(",", ""))
    if not m:
        return None
    n = float(m.group())
    shown_unit = re.sub(r"[\d.\-+/\s]", "", text or "").lower()
    if shown_unit in ("s", "khz") and unit.lower() in ("ms", "hz"):
        n *= 1000.0
    return n


def _step(ends: list[str], unit: str) -> float:
    """One step of the finer end display, each end's in its own unit ("20 Hz" against "20.0 kHz"
    is 1 Hz), in the parameter's unit."""
    def one(shown: str) -> float:
        m = re.search(r"\d\.(\d+)", shown or "")
        letters = re.sub(r"[\d.\-+/\s]", "", shown or "").lower()
        return 10.0 ** -(len(m.group(1)) if m else 0) * (1000.0 if letters in ("s", "khz") and unit.lower() in ("ms", "hz") else 1.0)
    return min(one(e) for e in ends)


@_goldens.needs(*KEYS)
class RangeFactsTest(unittest.TestCase):
    def test_every_table_range_is_the_staged_end_displays(self):
        tables = {t.name: t for t in load_tables().values()}
        checked, seen = 0, set()
        for key in KEYS:
            ends = _goldens.fact(key, "slider_ends")
            plugin = _goldens.fact(key, "plugin")
            for name, rows in ({plugin: ends} if plugin else ends).items():
                table = tables.get(name)
                self.assertIsNotNone(table, f"{key}: `slider_ends` names {name!r}, which no table is")
                numeric = {n for n, (lo, hi) in rows.items() if _number(lo, "") is not None and _number(hi, "") is not None}
                if table.state != "text" and any(p.name in numeric and not p.choices for p in table.params):
                    with self.subTest(f"{table.name} carries ranges"):      # a text state is read, never written
                        self.assertTrue(any(p.min is not None for p in table.params))
                for p in table.params:
                    if p.min is None or p.name not in rows or p.named:      # a named end's range is its own (`tests/goldens/test_stereo_rows.py`)
                        continue
                    lo, hi = (_number(e, p.unit) for e in rows[p.name])
                    with self.subTest(f"{table.name} {p.name}"):
                        self.assertIsNotNone(lo)
                        self.assertIsNotNone(hi)
                        self.assertAlmostEqual(p.min, min(lo, hi), places=3)
                        self.assertAlmostEqual(p.max, max(lo, hi), places=3)
                        checked += 1
                        seen.add((table.name, p.name))
        ranged = {(t.name, p.name) for t in tables.values() if t.state != "text" for p in t.params if p.min is not None and not p.named}
        self.assertEqual(sorted(ranged - seen), [], "ranges with no staged end displays behind them")
        self.assertGreater(checked, 0)

    def test_the_save_read_holds_each_ranged_rows_default_in_its_word(self):
        """On the channel the ends were read on, the word is the table's default to one display step
        (Logic truncates its displays)."""
        tables, seen = load_tables(), set()
        for key in KEYS:
            ends, plugin = _goldens.fact(key, "slider_ends"), _goldens.fact(key, "plugin")
            by_plugin, done = ({plugin: ends} if plugin else ends), set()
            for ref, payload in slot_payloads(project_data(_goldens.path(key))):
                table = table_of(tables, payload)
                if table is None or table.name not in by_plugin or table.name in done or ref.channel != _goldens.fact(key, "channel"):
                    continue
                done.add(table.name)
                words, rows = decode_payload(table, payload), by_plugin[table.name]
                for p in table.params:
                    if p.min is None or p.named or p.choices or p.name not in rows or not isinstance(p.default, (int, float)):
                        continue
                    with self.subTest(key, row=f"{table.name} {p.name}"):
                        self.assertLessEqual(abs(words[p.name] - p.default), _step(rows[p.name], p.unit) + 1e-6,
                                             (words[p.name], p.default, p.unit, rows[p.name]))
                        seen.add((table.name, p.name))
        ranged = {(t.name, p.name) for t in tables.values() if t.state != "text" for p in t.params
                  if p.min is not None and not p.named and not p.choices and isinstance(p.default, (int, float))}
        self.assertEqual(sorted(ranged - seen), [], "ranged rows no save's word was checked for")


if __name__ == "__main__":
    unittest.main()
