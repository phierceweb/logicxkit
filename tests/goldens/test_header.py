"""Track header components: every bit pinned by Logic's own single-toggle saves.

The real-file part of tests/logic/test_header.py; skips without the owner's files."""

import plistlib
import struct
import unittest
from pathlib import Path
import _paths  # noqa: F401
from logicxkit.logic.services.header import (
    BLOB_LEN,
    components_of,
    read_components,
    with_components,
    write_components,
)

E = _paths.RESOURCES / "experiments"
SAVES = ["13-header-baseline", "14-header-no-track-numbers", "15-header-volume-on", "16-header-onoff-off",
         "17-header-mute-off", "18-header-solo-off", "19-header-protect-on", "20-header-freeze-off",
         "21-header-record-off", "22-header-monitor-off", "23-header-pansend-on", "24-header-namecol-on",
         "25-header-csbars-off", "26-header-colorbars-off", "27-header-groove-on", "28-header-icons-off",
         "29-header-alts-off"]
TOGGLES = [None, ("Track Numbers", False), ("Volume", True), ("On/Off", False), ("Mute", False), ("Solo", False),
           ("Track Protect", True), ("Freeze", False), ("Record Enable", False), ("Input Monitoring", False),
           ("Pan/Send", True), ("Additional Name Column", True), ("Control Surface Bars", False),
           ("Track Color Bars", False), ("Groove Track", True), ("Track Icons", False), ("Track Alternatives", False)]
BASELINE = {"On/Off": True, "Mute": True, "Solo": True, "Track Protect": False, "Freeze": True, "Record Enable": True,
            "Input Monitoring": True, "Volume": False, "Pan/Send": False, "Additional Name Column": False,
            "Control Surface Bars": True, "Track Numbers": True, "Track Color Bars": True, "Groove Track": False,
            "Track Icons": True, "Track Alternatives": True}


@unittest.skipIf(not all((E / f"{n}.logicx").exists() for n in SAVES), "the header saves are not present")
class GoldenHeaderTest(unittest.TestCase):
    """Seventeen Logic saves, one toggle each: the reader must see each toggle, and the
    writer must reproduce Logic's flag words and width from the save before it."""

    @staticmethod
    def blob(name: str) -> bytes:
        from logicxkit.logic.services.header import _find_blob
        p = sorted((E / f"{name}.logicx").glob("Alternatives/*/DisplayState.plist"))[0]
        return _find_blob(plistlib.loads(p.read_bytes()))

    def test_each_save_reads_as_its_toggle(self):
        state = dict(BASELINE)
        self.assertEqual(components_of(self.blob(SAVES[0])), state)
        for name, toggle in zip(SAVES[1:], TOGGLES[1:], strict=True):
            state[toggle[0]] = toggle[1]
            self.assertEqual(components_of(self.blob(name)), state, name)

    def test_the_writer_reproduces_logics_words_and_width(self):
        for prev, name, toggle in zip(SAVES[:-1], SAVES[1:], TOGGLES[1:], strict=True):
            ours = with_components(self.blob(prev), {toggle[0]: toggle[1]})
            logic = self.blob(name)
            for at in (38, 58, 68, 70):
                self.assertEqual(struct.unpack_from("<H", ours, at)[0], struct.unpack_from("<H", logic, at)[0], (name, at))

    def test_write_components_edits_both_files_on_a_copy(self):
        import shutil
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "x.logicx"
            shutil.copytree(E / f"{SAVES[0]}.logicx", copy)
            alt = copy / "Alternatives/000"
            state = write_components(alt, {"Volume": True, "Track Numbers": False})
            self.assertEqual((state["Volume"], state["Track Numbers"]), (True, False))
            self.assertEqual(read_components(alt), state)
            archive = plistlib.loads((alt / "DisplayStateArchive").read_bytes())
            blobs = [o for o in archive["$objects"] if isinstance(o, bytes) and len(o) == BLOB_LEN]
            self.assertTrue(any(components_of(b) == state for b in blobs))


if __name__ == "__main__":
    unittest.main()
