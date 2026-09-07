"""Track header components: every bit pinned by Logic's own single-toggle saves."""

import struct
import unittest
import _paths  # noqa: F401
from logicxkit.logic.services.header import (
    BLOB_LEN,
    COMPONENTS,
    components_of,
    header_width,
    with_components,
)

BASELINE = {"On/Off": True, "Mute": True, "Solo": True, "Track Protect": False, "Freeze": True, "Record Enable": True,
            "Input Monitoring": True, "Volume": False, "Pan/Send": False, "Additional Name Column": False,
            "Control Surface Bars": True, "Track Numbers": True, "Track Color Bars": True, "Groove Track": False,
            "Track Icons": True, "Track Alternatives": True}


def synthetic() -> bytes:
    blob = bytearray(BLOB_LEN)
    struct.pack_into("<H", blob, 58, 0x1180)
    struct.pack_into("<H", blob, 68, 0x8029)
    struct.pack_into("<H", blob, 70, 0x948F)
    struct.pack_into("<H", blob, 38, 292)
    return bytes(blob)


class BlobTest(unittest.TestCase):
    def test_the_baseline_words_read_as_the_screenshot(self):
        self.assertEqual(components_of(synthetic()), BASELINE)

    def test_every_component_has_its_own_bit(self):
        self.assertEqual(len({(a, b) for a, b, _s, _w in COMPONENTS.values()}), len(COMPONENTS))

    def test_writing_round_trips_and_touches_only_flags_and_width(self):
        blob = synthetic()
        out = with_components(blob, {"Volume": True, "Track Numbers": False})
        state = components_of(out)
        self.assertEqual((state["Volume"], state["Track Numbers"]), (True, False))
        self.assertEqual([i for i in range(BLOB_LEN) if blob[i] != out[i] and i not in (38, 39, 58, 59, 68, 69, 70, 71)], [])
        self.assertEqual(struct.unpack_from("<H", out, 38)[0], 292 - 12 + 128)
        self.assertEqual(with_components(out, {"Volume": False, "Track Numbers": True}), blob)

    def test_unknown_name_is_refused(self):
        with self.assertRaises(ValueError):
            with_components(synthetic(), {"Mutee": True})

    def test_width_is_the_base_plus_the_shown_widths(self):
        self.assertEqual(header_width(BASELINE), 292)
        self.assertEqual(header_width({n: False for n in COMPONENTS}), 109)


if __name__ == "__main__":
    unittest.main()
