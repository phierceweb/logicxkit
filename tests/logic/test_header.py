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
        self.assertEqual(header_width(BASELINE, 109), 292)
        self.assertEqual(header_width({n: False for n in COMPONENTS}, 109), 180)    # the floor


class ClampedWidthTest(unittest.TestCase):
    HIDDEN = ["Volume", "Pan/Send", "Record Enable", "Track Icons"]

    def _header(self, blob: bytes, show: list[str]) -> str:
        import plistlib
        import tempfile
        from argparse import Namespace
        from pathlib import Path
        from unittest import mock
        from logicxkit.logic._header import cmd_header
        from logicxkit.logic.services.header import BLOB_KEY
        with tempfile.TemporaryDirectory() as tmp:
            alt = Path(tmp) / "Song.logicx" / "Alternatives" / "000"
            alt.mkdir(parents=True)
            (alt / "DisplayState.plist").write_bytes(plistlib.dumps({BLOB_KEY: blob}, fmt=plistlib.FMT_BINARY))
            with mock.patch("builtins.print") as printed:
                rc = cmd_header(Namespace(project=str(alt.parents[1]), out=str(Path(tmp) / "out"),
                                          show=show, hide=None, src=None))
        self.assertEqual(rc, 0)
        return "\n".join(" ".join(map(str, c.args)) for c in printed.call_args_list)

    def test_widening_from_the_floor_says_the_width_is_estimated(self):
        clamped = with_components(WidthTest.blank_base(), dict.fromkeys(self.HIDDEN, False))
        self.assertEqual(struct.unpack_from("<H", clamped, 38)[0], 180)
        self.assertIn("estimated", self._header(clamped, self.HIDDEN))

    def test_an_unclamped_width_is_not_flagged(self):
        self.assertNotIn("estimated", self._header(WidthTest.blank_base(), ["On/Off"]))


if __name__ == "__main__":
    unittest.main()


class WidthTest(unittest.TestCase):
    """The width at +38 is the file's own name-column width plus the shown components', never
    below 180."""

    @staticmethod
    def blank_base() -> bytes:
        blob = bytearray(BLOB_LEN)
        struct.pack_into("<H", blob, 58, 0x1180)      # Track Numbers shown
        struct.pack_into("<H", blob, 68, 0x0006)      # Volume, Pan/Send
        struct.pack_into("<H", blob, 70, 0x008F)      # Mute, Record Enable, Solo, Track Icons, Input Monitoring
        struct.pack_into("<H", blob, 38, 325)         # 33 + 292
        return bytes(blob)

    def test_the_width_grows_from_the_files_own_base(self):
        out = with_components(self.blank_base(), {"On/Off": True})
        self.assertEqual(struct.unpack_from("<H", out, 38)[0], 347)

    def test_the_width_never_drops_below_the_floor(self):
        out = with_components(self.blank_base(), {"Volume": False, "Pan/Send": False, "Record Enable": False,
                                                  "Track Icons": False})      # 33 + 83 would be 116
        self.assertEqual(struct.unpack_from("<H", out, 38)[0], 180)
