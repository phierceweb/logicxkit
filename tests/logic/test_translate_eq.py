"""An EQ's bands across EQs: Pro-Q 4's state read by its band layout, Channel EQ read by its
table, and bands landing in Channel EQ's slots by shape with the rest reported."""

import math
import plistlib
import struct
import unittest

from logicxkit.logic.services.translate import load_maps, map_for, plan, read_settings
from logicxkit.logic.services.translate_eq import Band
from logicxkit.utils.data import PACKAGED

MAPS = load_maps([PACKAGED / "translate"])
PROQ = next(m for m in MAPS if m.plugin == "Pro-Q 4")
CHEQ = next(m for m in MAPS if m.plugin == "Channel EQ")


def proq_payload(bands: dict[int, dict]) -> bytes:
    """A Pro-Q 4 slot payload: the FFBS blob (600 values by id) inside the AU ClassInfo plist."""
    values = [0.0] * 600
    for n, b in bands.items():
        base = (n - 1) * 23
        values[base + 0] = 1.0
        values[base + 1] = 0.0 if b.get("off") else 1.0
        values[base + 2] = math.log2(b["frequency"])
        values[base + 3] = b.get("gain", 0.0)
        values[base + 4] = b.get("q", 0.5)
        values[base + 5] = float(b.get("shape", 0))
        values[base + 6] = float(b.get("slope", 2))
        values[base + 9] = b.get("dynamic_range", 0.0)
        values[base + 10] = 1.0
    blob = b"FFBS" + struct.pack("<II", 1, 600) + struct.pack("<600f", *values) + b"FQ4p" + bytes(8)
    code = lambda s: int.from_bytes(s.encode(), "big")          # noqa: E731
    plist = plistlib.dumps({"type": code("aumf"), "subtype": code("FQ4p"), "manufacturer": code("FabF"), "version": 1,
                            "name": "Default Setting", "FabFilterPluginState": blob}, fmt=plistlib.FMT_XML)
    return bytes(180) + plist


class ReadProQ4Test(unittest.TestCase):
    def test_bands_read_with_their_shapes_units_and_curves(self):
        payload = proq_payload({1: {"shape": 2, "frequency": 80.0, "slope": 4},
                                2: {"shape": 0, "frequency": 1000.0, "gain": 3.0, "q": 0.5},
                                3: {"shape": 3, "frequency": 8000.0, "gain": -2.0, "dynamic_range": -6.0, "off": True}})
        self.assertIs(map_for(payload, MAPS), PROQ)
        s = read_settings(payload, PROQ)
        self.assertEqual([b.shape for b in s.bands], ["low_cut", "bell", "high_shelf"])
        self.assertAlmostEqual(s.bands[0].frequency, 80.0, places=3)
        self.assertEqual(s.bands[0].slope, 24)
        self.assertEqual((s.bands[1].gain, round(s.bands[1].q, 3), s.bands[1].on), (3.0, 1.0, True))
        self.assertEqual((s.bands[2].dynamic, s.bands[2].on, s.bands[2].number), (True, False, 3))
        self.assertIsNone(s.master)


class PlanChannelEQTest(unittest.TestCase):
    def test_bands_land_by_shape_with_bells_by_rising_frequency(self):
        payload = proq_payload({1: {"shape": 2, "frequency": 80.0, "slope": 4},
                                2: {"shape": 0, "frequency": 1000.0, "gain": 3.04, "q": 0.5},
                                3: {"shape": 0, "frequency": 250.0, "gain": -4.0, "q": 0.62},
                                4: {"shape": 3, "frequency": 8000.0, "gain": -2.0},
                                5: {"shape": 4, "frequency": 16000.0},
                                6: {"shape": 5, "frequency": 60.0},
                                7: {"shape": 0, "frequency": 4000.0, "gain": 2.0},
                                8: {"shape": 0, "frequency": 500.0, "gain": 1.0},
                                9: {"shape": 0, "frequency": 2000.0, "gain": -1.0}})
        p = plan(read_settings(payload, PROQ), CHEQ)
        v = p.values
        self.assertEqual((v["Low Cut On/Off"], v["Low Cut Frequency"]), ("On", 80.0))
        self.assertEqual([v[f"Peak {n} Frequency"] for n in (1, 2, 3, 4)], [250.0, 500.0, 1000.0, 2000.0])
        self.assertEqual([v[f"Peak {n} Gain"] for n in (1, 2, 3, 4)], [-4.0, 1.0, 3.0, -1.0])          # 3.04 on the 0.1 dB grid
        self.assertEqual((v["High Shelf On/Off"], v["High Shelf Frequency"], v["High Shelf Gain"]), ("On", 8000.0, -2.0))
        self.assertEqual((v["High Cut On/Off"], v["High Cut Frequency"], v["Low Shelf On/Off"]), ("On", 16000.0, "Off"))
        notes = "\n".join(p.notes)
        self.assertIn("band 7 bell 4.00 kHz +2.0 dB Q 1.00: no slot of that shape in Channel EQ", notes)
        self.assertIn("band 6 notch 60 Hz Q 1.00: no analogue in Channel EQ", notes)
        self.assertIn("band 1 low cut 80 Hz Q 1.00 24 dB/oct: the slope stays Channel EQ's own", notes)

    def test_channel_eq_reads_back_through_its_table(self):
        floats = [0.0] * 52
        floats[1], floats[2], floats[4] = 1.0, 80.0, 0.71                    # low cut on, 80 Hz
        floats[9], floats[10], floats[11], floats[12] = 1.0, 1000.0, 3.0, 1.0  # peak 1
        floats[33] = 1.5
        p = bytearray(184 + 12 + 4 * 52)
        p[184:192] = b"GAMETSPP"
        struct.pack_into("<III", p, 172, 24 + 52 * 4, 1, 52)
        struct.pack_into("<I", p, 192, 236)
        struct.pack_into("<52f", p, 196, *floats)
        s = read_settings(bytes(p), CHEQ)
        by_shape = {b.shape: b for b in s.bands if b.on}
        self.assertEqual(sorted(by_shape), ["bell", "low_cut"])
        self.assertEqual((by_shape["bell"].frequency, by_shape["bell"].gain, by_shape["bell"].q), (1000.0, 3.0, 1.0))
        self.assertEqual(s.master, 1.5)


class BandLabelTest(unittest.TestCase):
    def test_labels(self):
        self.assertEqual(Band("bell", 1000.0, 3.0, 1.0, True).label(), "bell 1.00 kHz +3.0 dB Q 1.00")
        self.assertEqual(Band("low_cut", 80.0, 0.0, 0.71, False, 24).label(), "low cut 80 Hz Q 0.71 24 dB/oct (off)")


if __name__ == "__main__":
    unittest.main()
