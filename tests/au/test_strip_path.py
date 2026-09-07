"""decode_strip_path: flat file vs .logicx bundle, and the channel attribution the
bundle branch adds. The bundle branch had no coverage before this file."""

import os
import plistlib
import tempfile
import unittest
from pathlib import Path

from logicxkit.au.services.report import decode_strip_path

FAB = 0x46616254  # 'FabT' — any manufacturer; the static path needs no AU host


def _plist(manufacturer: int, name: str) -> bytes:
    return plistlib.dumps(
        {"manufacturer": manufacturer, "subtype": 0x51345F5F, "type": 0x61756678,
         "name": name, "version": 0, "data": b"\x00" * 16},
        fmt=plistlib.FMT_XML)


def _channel(label: bytes, *plists: bytes) -> bytes:
    """One OCuA channel block carrying the given embedded AU plists."""
    head = b"OCuA\x06\x00\x0e\x00" + b" " + label + b"\x00" * 32
    return head + b"".join(b"junk" + p for p in plists)


def _bundle(root: str, name: str, data: bytes, alts=("000",)) -> str:
    for alt in alts:
        d = Path(root, name, "Alternatives", alt)
        d.mkdir(parents=True)
        (d / "ProjectData").write_bytes(data if alt == alts[0] else b"")
    return str(Path(root, name))


class DecodeStripPathTest(unittest.TestCase):
    def test_flat_file_yields_states_without_channel(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "strip.cst")
            with open(p, "wb") as fh:
                fh.write(b"pad" + _plist(FAB, "One"))
            states = decode_strip_path(p, host=None)
        self.assertEqual(len(states), 1)
        self.assertNotIn("channel", states[0])

    def test_bundle_attributes_each_state_to_its_channel(self):
        data = (_channel(b"Audio 4", _plist(FAB, "One"))
                + _channel(b"Bus 5", _plist(FAB, "Two")))
        with tempfile.TemporaryDirectory() as d:
            states = decode_strip_path(_bundle(d, "song.logicx", data), host=None)
        self.assertEqual([s["channel"] for s in states], ["Audio 4", "Bus 5"])

    def test_unlabelled_block_attributes_to_the_question_sentinel(self):
        # channel_label returns "?", not None — the CLI prints it, so it must stay truthy
        data = _channel(b"Nope", _plist(FAB, "One"))
        with tempfile.TemporaryDirectory() as d:
            states = decode_strip_path(_bundle(d, "song.logicx", data), host=None)
        self.assertEqual([s["channel"] for s in states], ["?"])

    def test_state_before_any_channel_block_is_unattributed(self):
        data = b"lead" + _plist(FAB, "Early") + _channel(b"Audio 1", _plist(FAB, "Late"))
        with tempfile.TemporaryDirectory() as d:
            states = decode_strip_path(_bundle(d, "song.logicx", data), host=None)
        self.assertEqual([s["channel"] for s in states], [None, "Audio 1"])

    def test_bundle_reads_the_first_alternative(self):
        data = _channel(b"Audio 9", _plist(FAB, "One"))
        with tempfile.TemporaryDirectory() as d:
            # "001" is written empty; picking it instead of "000" would yield no states
            states = decode_strip_path(
                _bundle(d, "song.logicx", data, alts=("000", "001")), host=None)
        self.assertEqual([s["channel"] for s in states], ["Audio 9"])


if __name__ == "__main__":
    unittest.main()
