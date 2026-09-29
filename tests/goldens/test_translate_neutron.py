"""iZotope Neutron 5, dialled in Logic's Controls view, read through its three maps, and each
family carried into one of Logic's own — Logic showing the plans. Skips without the public corpus."""

import re
import unittest

import _goldens
from logicxkit.logic._edit import owner_by_label
from logicxkit.logic.services.insert import HEADER
from logicxkit.logic.services.transplant import slot_at
from logicxkit.logic.services.translate import load_maps, map_for, maps_for, plan, read_settings
from logicxkit.logicx import project_data
from logicxkit.utils.data import PACKAGED

MAPS = load_maps([PACKAGED / "translate"])


def _payload(key: str) -> bytes:
    data = project_data(_goldens.path(key))
    facts = _goldens.entry(key)["facts"]
    return slot_at(data, owner_by_label(data, facts["channel"]), facts["slot"]).raw[HEADER:]


def _number(text: str) -> float:
    return float(re.match(r"[-+]?\d+(?:\.\d+)?", text).group())


@_goldens.needs("neutron-base", "neutron-dialled")
class NeutronReadTest(unittest.TestCase):
    def test_a_fresh_instance_carries_three_families_and_no_eq_bands(self):
        found = maps_for(_payload("neutron-base"), MAPS)
        self.assertEqual([m.family for m in found], _goldens.entry("neutron-base")["facts"]["families"])
        self.assertEqual(read_settings(_payload("neutron-base"), found[1]).bands, [])

    def test_the_dialled_instance_reads_as_dialled(self):
        facts = _goldens.entry("neutron-dialled")["facts"]
        payload = _payload("neutron-dialled")
        by_family = {m.family: m for m in maps_for(payload, MAPS)}
        comp = read_settings(payload, by_family["compressor"]).values
        for name, want in facts["compressor"].items():
            with self.subTest(name):
                self.assertAlmostEqual(comp[name], want, places=1)
        gate = read_settings(payload, by_family["gate"])
        for name, want in facts["gate"].items():
            with self.subTest(name):
                self.assertAlmostEqual(gate.values[name], want, places=1)
        self.assertEqual(gate.notes, ["Neutron 5's Gate Expander is bypassed"])     # no Controls row switches it on
        self.assertEqual([b.label() for b in read_settings(payload, by_family["eq"]).bands], facts["bands"])


@_goldens.needs("neutron-dialled", "neutron-comp", "neutron-comp-resave-logic", "neutron-gate", "neutron-gate-resave-logic",
                "neutron-eq", "neutron-eq-resave-logic")
class NeutronCarryTest(unittest.TestCase):
    def _carried(self, family: str, ours: str, resave: str):
        source = _payload("neutron-dialled")
        src = next(m for m in maps_for(source, MAPS) if m.family == family)
        target = map_for(_payload(ours), MAPS)
        planned = plan(read_settings(source, src), target).values
        written = read_settings(_payload(ours), target)
        shown = _goldens.entry(resave)["facts"]["shown"]
        return planned, written, shown

    def test_the_compressor(self):
        planned, written, shown = self._carried("compressor", "neutron-comp", "neutron-comp-resave-logic")
        self.assertEqual((planned["Threshold"], planned["Ratio"], planned["Attack"], planned["Release"]), (-20.0, 2.9, 26.0, 120.0))
        self.assertAlmostEqual(written.values["ratio"], 2.9, places=5)
        for name, vocab in (("Threshold", "threshold"), ("Ratio", "ratio"), ("Attack", "attack"), ("Release", "release"), ("Make Up", "make_up"), ("Mix", "mix")):
            with self.subTest(name):
                self.assertAlmostEqual(_number(shown[name]), written.values[vocab], places=1)

    def test_the_gate(self):
        planned, written, shown = self._carried("gate", "neutron-gate", "neutron-gate-resave-logic")
        self.assertEqual((planned["Threshold"], planned["Hold"], planned["Hysteresis"]), (-100.0, 250.0, -0.5))
        for name, vocab in (("Threshold", "threshold"), ("Hysteresis", "hysteresis"), ("Attack", "attack"), ("Hold", "hold"), ("Release", "release")):
            with self.subTest(name):
                self.assertAlmostEqual(_number(shown[name]), written.values[vocab], places=1)

    def test_the_eq(self):
        planned, written, shown = self._carried("eq", "neutron-eq", "neutron-eq-resave-logic")
        self.assertEqual((planned["Peak 1 Frequency"], planned["High Shelf Gain"], planned["Peak 2 Q-Factor"]), (150.0, 3.0, 4.0))
        on = {b.shape: b for b in written.bands if b.on}
        self.assertEqual(sorted(on), ["bell", "high_shelf"])
        self.assertEqual([b.label() for b in written.bands if b.on],
                         ["bell 150 Hz -4.0 dB Q 1.50", "bell 3.00 kHz -6.0 dB Q 4.00", "high shelf 2.00 kHz +3.0 dB Q 2.00"])
        self.assertEqual((_number(shown["Peak 1 Frequency"]), _number(shown["Peak 2 Gain"]), _number(shown["High Shelf Q-Factor"])), (150.0, -6.0, 2.0))
        self.assertEqual((shown["Peak 3 On/Off"], shown["Low Cut On/Off"]), ("0", "0"))


if __name__ == "__main__":
    unittest.main()
