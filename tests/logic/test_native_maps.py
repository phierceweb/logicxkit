"""Every native map's `automation` table against the plug-in's parameter table: each row is a
table row and its curve ends where the table's range does, units ascend, values never fall, and
`per` is the rate the measured maps follow — 128 for a slider of up to 127 units, else the units
times 128/127 to the nearest quarter, Channel EQ's frequencies measured a quarter under it."""

import json
import unittest

from logicxkit.utils.data import PACKAGED

MAPS_DIR = PACKAGED / "translate"
TABLES_DIR = PACKAGED / "logic"
MEASURED_PER = {1050: 1058.0}


def rule_per(top: float) -> float:
    return 128.0 if top <= 127 else round(top * 128 / 127 * 4) / 4


def problems(m: dict, table: dict) -> list[str]:
    """What is wrong with one native map against its table; empty when nothing is."""
    rows = {p["name"]: p for p in table["params"]}
    out = []
    if m.get("type") != table["type"]:
        out.append(f"type {m.get('type')}, table {table['type']}")
    if m.get("variant") != table.get("variant"):
        out.append(f"variant {m.get('variant')}, table {table.get('variant')}")
    for name, a in m.get("automation", {}).items():
        p = rows.get(name)
        if p is None:
            out.append(f"{name}: not a row of {table['name']}")
            continue
        units = a["units"]
        pairs = list(zip(units, units[1:], strict=False))
        if any(u1 <= u0 for (u0, _v0), (u1, _v1) in pairs):
            out.append(f"{name}: units do not ascend")
        if any(v1 < v0 for (_u0, v0), (_u1, v1) in pairs):
            out.append(f"{name}: values fall")
        if any(round(v, 4) != v for _u, v in units):              # `land` compares values at four places
            out.append(f"{name}: a value past four places")
        lo, hi = units[0][1], units[-1][1]
        if (p.get("min") is not None and p["min"] != lo) or (p.get("max") is not None and p["max"] != hi):
            out.append(f"{name}: ends {lo}..{hi}, table {p.get('min')}..{p.get('max')}")
        top, per = units[-1][0], float(a.get("per", 128))
        if abs(per - MEASURED_PER.get(top, rule_per(top))) > 1e-9:
            out.append(f"{name}: per {per:g}, rule {MEASURED_PER.get(top, rule_per(top)):g}")
    return out


def native_maps() -> list[tuple[str, dict, dict]]:
    out = []
    for path in sorted(MAPS_DIR.glob("logic-*.json")):
        m = json.loads(path.read_text())
        out.append((path.stem, m, json.loads((TABLES_DIR / f"params-{m['type']}.json").read_text())))
    return out


class NativeMapFactsTest(unittest.TestCase):
    def test_the_packaged_maps_hold_every_fact(self):
        maps = native_maps()
        self.assertGreaterEqual(len(maps), 4)
        for stem, m, table in maps:
            with self.subTest(stem):
                self.assertEqual(problems(m, table), [])

    def test_the_three_output_maps_sample_every_unit(self):
        for stem, m, _table in native_maps():
            if m["type"] not in (243, 193, 199):
                continue
            for name, a in m["automation"].items():
                with self.subTest(stem, row=name):
                    units = [u for u, _v in a["units"]]
                    self.assertEqual(units, list(range(int(units[0]), int(units[-1]) + 1)))

    def test_the_check_can_fail(self):
        table = {"type": 199, "variant": 1020, "name": "Limiter",
                 "params": [{"index": 1, "name": "Gain", "min": -20.0, "max": 20.0}]}
        bad = {"type": 199, "variant": 1021,
               "automation": {"Gain": {"per": 130, "units": [[0, -20.0], [2, -19.00001], [1, -19.5], [3, 19.0]]},
                              "Nope": {"per": 128, "units": [[0, 0.0]]}}}
        found = problems(bad, table)
        for what in ("variant", "Gain: units do not ascend", "Gain: values fall", "Gain: ends -20.0..19.0", "Gain: per 130",
                     "Gain: a value past four places", "Nope: not a row"):
            with self.subTest(what):
                self.assertTrue(any(what in f for f in found), found)
        self.assertEqual(len(found), 7)
