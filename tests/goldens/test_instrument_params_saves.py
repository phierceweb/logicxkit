"""The parameter tables against the saves past the defaults/spots pair: coded saves
(`instrument-params-<name>-code-base`, `-code0`…; `effectcheck-*`), the display Logic showed
at each placed parameter's default, and the one-row series (`-row00`…, `-again00`…)."""

import json
import unittest

import _goldens
from _instparams import CODED, ROWS, _block, _payload, _series, _series_of, _slug_and_prefix, _unit_scaled, _word
from logicxkit.logic.services.mixer.plugin_names import PLUGIN_NAMES
from logicxkit.logic.services.mixer.plugin_params import int_word, load_tables, table_for
from logicxkit.logicx import project_data
from logicxkit.utils.data import PACKAGED


def _channel(defaults: str) -> str:
    """The channel the measured plug-in sits on: Inst 1, or the output channel for Mastering Assistant."""
    return _goldens.fact(defaults, "channel") or "Inst 1"


@_goldens.needs(*CODED)
class CodedSavesTest(unittest.TestCase):
    """Rows a table could not place by value were told apart by a binary code: row i was moved in
    every coded save whose bit i has set (`instrument-params-<name>-code-base`, `-code0` …). A
    parameter placed that way changes between consecutive saves exactly on its code's bits."""

    @classmethod
    def setUpClass(cls):
        cls.tables = load_tables([PACKAGED / "logic"])

    def test_every_coded_run_placed_something_but_over_a_text_state(self):
        """Over a float block a coded run names rows. Over Alchemy's text state it names none:
        a row's move changes many keys and the single answers are other parameters' keys."""
        self.assertTrue(CODED)
        for key in CODED:
            with self.subTest(key):
                slug, prefix = _slug_and_prefix(key)
                defaults = f"{prefix}{slug}-defaults"
                before = _block(project_data(_goldens.path(defaults)), _channel(defaults), defaults)
                table = table_for(self.tables, before[0], before[1])
                coded = [p for p in table.params if p.evidence == "code"]
                codes = _goldens.fact(key, "codes")
                every = {n for k in CODED if _slug_and_prefix(k) == (slug, prefix) for n in _goldens.fact(k, "codes")}
                self.assertTrue(len(codes) >= 1)
                if table.state == "text":
                    self.assertEqual(coded, [])
                    continue
                self.assertTrue(all(p.name in every for p in coded), [p.name for p in coded if p.name not in every])

    def test_a_code_carried_by_one_word_alone_names_that_word(self):
        """The oracle the tables must answer to: where exactly one block word changes on a row's
        code and no other, the table names that row at that word — or names nothing there. Where a
        one-row save names the word as another row's, the coded series moved a row it did not
        record (ES2's MM9 Source moved Env2 Decay's word, 99 to 160): its row is placed by no code."""
        for key in CODED:
            slug, prefix = _slug_and_prefix(key)
            defaults = f"{prefix}{slug}-defaults"
            head = _block(project_data(_goldens.path(defaults)), _channel(defaults), defaults)
            table = table_for(self.tables, head[0], head[1])
            if table is None or table.state == "text":
                continue
            bits, codes = _goldens.fact(key, "bits"), _goldens.fact(key, "codes")
            saves = [key] + [f"{prefix}{slug}-{_series_of(key)}{b}" for b in range(bits)]
            series = [_block(project_data(_goldens.path(k)), _channel(defaults), defaults)[2] for k in saves]
            n = min(map(len, series))
            carried: dict[int, list[int]] = {}
            for j in range(n):
                code = sum(1 << b for b in range(bits) if series[b + 1][j] != series[b][j])
                if code:
                    carried.setdefault(code, []).append(j)
            by_index = {p.index: p for p in table.params if p.offset is None}
            coded = {p.name for p in table.params if p.evidence == "code"}
            rows = {code: name for name, code in codes.items()}
            for code, words in carried.items():
                if len(words) != 1 or code not in rows:
                    continue
                named = by_index.get(words[0])
                with self.subTest(f"{slug} {rows[code]} -> word {words[0]}"):
                    if named is not None and named.evidence == "row" and named.name != rows[code]:
                        self.assertNotIn(rows[code], coded)
                    elif named is not None:
                        self.assertEqual(named.name, rows[code])

    def test_a_coded_parameter_changes_on_its_codes_bits_alone(self):
        """In every series that lists it, but one whose `superseded` fact names the row: there the
        row's word moved on other rows' codes (Ultrabeat's second series), and a series that moves
        it on the row's own code must exist."""
        held: set[tuple[str, str]] = set()
        superseded: set[tuple[str, str]] = set()
        for key in CODED:
            slug, prefix = _slug_and_prefix(key)
            defaults = f"{prefix}{slug}-defaults"
            bits, codes = _goldens.fact(key, "bits"), _goldens.fact(key, "codes")
            saves = [key] + [f"{prefix}{slug}-{_series_of(key)}{b}" for b in range(bits)]
            payloads = [_payload(project_data(_goldens.path(k)), _channel(defaults), defaults) for k in saves]
            head = _block(project_data(_goldens.path(key)), _channel(defaults), defaults)
            table = table_for(self.tables, head[0], head[1])
            gone = set(_goldens.fact(key, "superseded", ()))
            for p in table.params:
                if p.evidence != "code" or p.name not in codes or p.offset is None and table.state == "text":
                    continue
                pattern = sum(1 << b for b in range(bits) if _word(payloads[b + 1], p) != _word(payloads[b], p))
                if p.name in gone:
                    superseded.add((slug, p.name))
                    continue
                with self.subTest(f"{key} {p.name}"):
                    self.assertEqual(pattern, codes[p.name])
                held.add((slug, p.name))
        self.assertEqual(sorted(superseded - held), [], "a superseded row no other series moves on its code")


SPOTS = tuple(k for k, e in _goldens._read(_goldens.PUBLIC).items() if k.endswith("-spots") and isinstance(e, dict))


@_goldens.needs(*SPOTS)
class SpotsDisplayTest(unittest.TestCase):
    def test_every_coded_row_had_a_display_of_its_own_move(self):
        """A coded series can record the wrong row, and every such row had no display of its own
        move in the plug-in's spots save (ES2's Sine Level), so a coded row is named only with one."""
        moved: dict[str, dict] = {}
        for key in SPOTS:
            moved.setdefault(_goldens.fact(key, "plugin"), {}).update(_goldens.fact(key, "moved") or {})
        unchecked = []
        for f in sorted((PACKAGED / "logic").glob("params-*.json")):
            t = json.loads(f.read_text())
            unchecked += [f"{t['name']} {p['name']}" for p in t["params"] if p.get("evidence") == "code"
                          and not str((moved.get(t["name"], {}).get(p["name"]) or {}).get("before", "")).strip()]
        self.assertEqual(unchecked, [])


class DefaultShownTest(unittest.TestCase):
    """A parameter placed by code, row or order carries the display Logic showed at its default;
    the word, scaled, must read as that number, or the placement is a guess."""

    def test_every_placed_parameters_default_reads_as_logic_showed(self):
        import re
        off = []
        for f in sorted((PACKAGED / "logic").glob("params-*.json")):
            t = json.loads(f.read_text())
            for p in t["params"]:
                shown = p.get("shown")
                if shown is None or p.get("choices"):
                    continue
                frac = re.match(r"^\s*(\d+)/(\d+)\b", shown)
                m = re.match(r"^\s*([-+]?\d+(?:\.\d+)?)", shown)
                if not (frac or m) or not isinstance(p.get("default"), (int, float)):
                    continue
                want = int(frac.group(1)) / int(frac.group(2)) if frac else float(m.group(1))
                default = int_word(p["default"]) if p.get("kind") == "int" and p.get("offset") is None else p["default"]
                word = float(default) * p.get("scale", 1.0)
                if abs(want - word) > max(0.011, abs(want) * 0.002) and not _unit_scaled(p.get("unit", ""), shown, want, word):
                    off.append(f"{t['name']} {p['name']}: word {p['default']} shown {shown!r} ({p['evidence']})")
        self.assertEqual(off, [])


@_goldens.needs(*ROWS)
class OneRowSavesTest(unittest.TestCase):
    """Rows the coded saves left were moved one per save (`instrument-params-<name>-row00` the
    base, `-row01`… each the save before with one more row moved; an `-again` series for the
    rows the first one showed the value pass had mislabelled): a parameter placed that way
    (evidence `row`) changes between the save before its row's and its row's."""

    @classmethod
    def setUpClass(cls):
        cls.tables = load_tables([PACKAGED / "logic"])

    def test_every_row_of_a_run_is_placed_or_still_listed_unmapped(self):
        """A row that moved no word of its own (Drum Synth's Key Tracking) stays on the table's
        unmapped list; none is dropped on the quiet."""
        self.assertTrue(ROWS)
        for key in ROWS:
            with self.subTest(key):
                slug, _name = _series(key)
                defaults = f"instrument-params-{slug}-defaults"
                head = _block(project_data(_goldens.path(defaults)), _channel(defaults), defaults)
                table = table_for(self.tables, head[0], head[1])
                stem = f"params-{head[0]}" if table.variant is None or table.name == PLUGIN_NAMES.get(head[0]) else f"params-{head[0]}v{head[1]}"
                unmapped = json.loads((PACKAGED / "logic" / f"{stem}.json").read_text())["unmapped"]
                placed = {p.name for p in table.params if p.evidence == "row"}
                rows = set(_goldens.fact(key, "rows"))
                every_run = {r for k in ROWS if _series(k)[0] == slug for r in _goldens.fact(k, "rows")}
                self.assertTrue(placed <= every_run, sorted(placed - every_run))
                self.assertEqual(rows - placed - set(unmapped) - {p.name for p in table.params}, set())

    def test_a_word_a_one_row_save_moves_alone_is_that_rows_or_unnamed(self):
        """A save that moved one row and changed one word has named that word: the table may
        call it that row's, or nobody's (a word two rows each move alone is Logic's own), never
        another row's — whatever evidence placed the other row there."""
        for key in ROWS:
            slug, series = _series(key)
            defaults = f"instrument-params-{slug}-defaults"
            rows = _goldens.fact(key, "rows")
            saves = [key] + [f"instrument-params-{slug}-{series}{i:02d}" for i in range(1, len(rows) + 1)]
            floats = [_block(project_data(_goldens.path(k)), _channel(defaults), defaults)[2] for k in saves]
            head = _block(project_data(_goldens.path(key)), _channel(defaults), defaults)
            by_index = {p.index: p for p in table_for(self.tables, head[0], head[1]).params if p.offset is None}
            for i, row in enumerate(rows, start=1):
                moved = [j for j in range(min(len(floats[i]), len(floats[i - 1]))) if floats[i][j] != floats[i - 1][j]]
                if len(moved) == 1 and moved[0] in by_index:
                    with self.subTest(f"{slug} {series}{i:02d} {row}"):
                        self.assertEqual(by_index[moved[0]].name, row,
                                         f"word {moved[0]} moved alone when {row!r} moved")

    def test_a_row_parameter_changes_at_its_own_save(self):
        for key in ROWS:
            slug, series = _series(key)
            defaults = f"instrument-params-{slug}-defaults"
            rows = _goldens.fact(key, "rows")
            saves = [key] + [f"instrument-params-{slug}-{series}{i:02d}" for i in range(1, len(rows) + 1)]
            payloads = [_payload(project_data(_goldens.path(k)), _channel(defaults), defaults) for k in saves]
            head = _block(project_data(_goldens.path(key)), _channel(defaults), defaults)
            table = table_for(self.tables, head[0], head[1])
            for p in table.params:
                if p.evidence != "row" or p.name not in rows:
                    continue
                i = rows.index(p.name) + 1
                with self.subTest(f"{slug} {p.name}"):
                    self.assertEqual(_goldens.fact(saves[i], "row"), p.name)
                    self.assertNotEqual(_word(payloads[i], p), _word(payloads[i - 1], p))


class UnitScaledTest(unittest.TestCase):
    def test_a_zero_word_does_not_read_as_any_display(self):
        self.assertFalse(_unit_scaled("", "5", 5.0, 0.0))
        self.assertFalse(_unit_scaled("ms", "0.5 s", 0.5, 0.0))

    def test_a_display_in_the_other_unit_reads_as_the_words(self):
        self.assertTrue(_unit_scaled("ms", "2.40 s", 2.4, 2400.0))        # a word in ms shown in s
        self.assertTrue(_unit_scaled("Hz", "8.0 kHz", 8.0, 8000.0))
        self.assertFalse(_unit_scaled("s", "2.40 s", 2.4, 2400.0))        # a unit of s over a word in ms is wrong
        self.assertFalse(_unit_scaled("kHz", "8.0 kHz", 8.0, 8000.0))
        self.assertTrue(_unit_scaled("%", "50 %", 50.0, 0.5))


if __name__ == "__main__":
    unittest.main()
