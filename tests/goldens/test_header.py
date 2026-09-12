"""Track header components: every bit pinned by Logic's own single-toggle saves.

The real-file part of tests/logic/test_header.py. Seventeen ordinal keys: `header-00` carries
the full set as `components`; each later key carries the one `toggle` its save made, so any
corpus can supply the sequence from its own base."""

import plistlib
import struct
import unittest
from pathlib import Path

import _goldens
from logicxkit.logic.services.header import (
    BLOB_LEN,
    components_of,
    read_components,
    with_components,
    write_components,
)

KEYS = [f"header-{n:02d}" for n in range(17)]      # header-00 is the base; each later key flips one component
PATHS = {k: _goldens.path(k) for k in KEYS}


def blob(key: str) -> bytes:
    from logicxkit.logic.services.header import _find_blob
    p = sorted(PATHS[key].glob("Alternatives/*/DisplayState.plist"))[0]
    return _find_blob(plistlib.loads(p.read_bytes()))


@unittest.skipUnless(all(PATHS.values()), "the header saves are not present")
class GoldenHeaderTest(unittest.TestCase):
    """Seventeen Logic saves, one toggle each: the reader must see each toggle, and the
    writer must reproduce Logic's flag words and width from the save before it."""

    def test_each_save_reads_as_its_toggle(self):
        state = dict(_goldens.fact(KEYS[0], "components"))
        self.assertEqual(components_of(blob(KEYS[0])), state)
        for key in KEYS[1:]:
            name, on = _goldens.fact(key, "toggle")
            state[name] = on
            self.assertEqual(components_of(blob(key)), state, key)

    def test_the_writer_reproduces_logics_words_and_width(self):
        for prev, key in zip(KEYS[:-1], KEYS[1:], strict=True):
            name, on = _goldens.fact(key, "toggle")
            ours, logic = with_components(blob(prev), {name: on}), blob(key)
            for at in (38, 58, 68, 70):
                self.assertEqual(struct.unpack_from("<H", ours, at)[0], struct.unpack_from("<H", logic, at)[0], (key, at))

    def test_write_components_edits_both_files_on_a_copy(self):
        import shutil
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "x.logicx"
            shutil.copytree(PATHS[KEYS[0]], copy)
            alt = copy / "Alternatives/000"
            state = write_components(alt, {"Volume": True, "Track Numbers": False})
            self.assertEqual((state["Volume"], state["Track Numbers"]), (True, False))
            self.assertEqual(read_components(alt), state)
            archive = plistlib.loads((alt / "DisplayStateArchive").read_bytes())
            blobs = [o for o in archive["$objects"] if isinstance(o, bytes) and len(o) == BLOB_LEN]
            self.assertTrue(any(components_of(b) == state for b in blobs))


if __name__ == "__main__":
    unittest.main()
