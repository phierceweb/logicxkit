"""Neural DSP plugin-state decode: AU plist discovery, NDSP filtering, and
file-level reading. The JUCE container formats themselves are covered in
tests/au/test_juce.py.

Golden tests run against the real strips and templates and auto-skip when absent."""

import os
import plistlib
import struct
import tempfile
import unittest
from logicxkit.logic import find_au_plists, neural_states, read_neural

NDSP = 0x4E445350  # 'NDSP'

SLO_X = 0x4E534C58  # 'NSLX'


def vc2(xml: str) -> bytes:
    raw = xml.encode()
    return b"VC2!" + struct.pack("<I", len(raw) + 1) + raw + b"\x00"


def _cint(n: int) -> bytes:
    """JUCE compressed int: byte-count then that many LE bytes."""
    if n == 0:
        return b"\x00"
    nbytes = (n.bit_length() + 7) // 8
    return bytes([nbytes]) + n.to_bytes(nbytes, "little")


def _var_str(s: str) -> bytes:
    payload = b"\x05" + s.encode() + b"\x00"
    return _cint(len(payload)) + payload


def _var_double(v: float) -> bytes:
    return _cint(9) + b"\x04" + struct.pack("<d", v)


def _tree(type_: str, props: list[tuple[str, bytes]], children: list[bytes]) -> bytes:
    out = type_.encode() + b"\x00" + _cint(len(props))
    for name, var in props:
        out += name.encode() + b"\x00" + var
    out += _cint(len(children))
    return out + b"".join(children)


def _param(pid: str, value: float) -> bytes:
    return _tree("PARAM", [("id", _var_str(pid)), ("value", _var_double(value))], [])


def tree_state() -> bytes:
    return _tree(
        "neural_dsp_test",
        [("tempo", _var_double(210.0)), ("presetNameProp", _var_str("Default"))],
        [_param("ampBass", 0.71), _param("gateThreshold", -80.0),
         _tree("midi_mappings", [("plugin_name", _var_str("Soldano SLO-100"))], [])],
    )

APP_MODEL = (
    '<?xml version="1.0" encoding="UTF-8"?> '
    '<appModel pluginVersion="1.0.0" presetUid="42"><subModels>'
    '<parameters gateThreshold="-77.5" gateActive="true"><subModels>'
    '<ampParameters sectionActive="true"><subModels>'
    '<amp ampBass="0.71" ampBright="true"/>'
    "</subModels></ampParameters></subModels></parameters>"
    "</subModels></appModel>"
)


def au_plist(manufacturer: int, subtype: int, state: bytes) -> bytes:
    return plistlib.dumps(
        {"manufacturer": manufacturer, "subtype": subtype, "type": 0x61756678,
         "name": "Untitled", "version": 0, "data": b"\x00" * 16,
         "jucePluginState": state},
        fmt=plistlib.FMT_XML)


def embedded(*plists: bytes) -> bytes:
    out = b"\x00\x01junk-before"
    for p in plists:
        out += p + b"\xff\xfejunk-between"
    return out


class FindAuPlistsTest(unittest.TestCase):
    def test_finds_and_parses_embedded_plists(self):
        data = embedded(au_plist(NDSP, SLO_X, vc2(APP_MODEL)))
        hits = find_au_plists(data)
        self.assertEqual(len(hits), 1)
        off, pl = hits[0]
        self.assertGreater(off, 0)
        self.assertEqual(pl["manufacturer"], NDSP)

    def test_ignores_non_plist_xml(self):
        data = b'junk<?xml version="1.0"?><notaplist/>more'
        self.assertEqual(find_au_plists(data), [])


class NeuralStatesTest(unittest.TestCase):
    def test_xml_format_state(self):
        data = embedded(au_plist(NDSP, SLO_X, vc2(APP_MODEL)))
        states = neural_states(data)
        self.assertEqual(len(states), 1)
        s = states[0]
        self.assertEqual(s["format"], "xml")
        self.assertEqual(s["subtype"], "NSLX")
        self.assertEqual(s["meta"]["pluginVersion"], "1.0.0")
        self.assertEqual(s["sections"]["amp"]["ampBass"], 0.71)
        self.assertIs(s["sections"]["amp"]["ampBright"], True)
        self.assertEqual(s["sections"]["parameters"]["gateThreshold"], -77.5)

    def test_tree_format_state(self):
        data = embedded(au_plist(NDSP, SLO_X, tree_state()))
        s = neural_states(data)[0]
        self.assertEqual(s["format"], "tree")
        self.assertEqual(s["meta"]["plugin_name"], "Soldano SLO-100")
        self.assertEqual(s["meta"]["presetNameProp"], "Default")
        self.assertAlmostEqual(s["sections"]["params"]["ampBass"], 0.71)
        self.assertEqual(s["sections"]["params"]["gateThreshold"], -80.0)

    def test_non_neural_manufacturer_skipped(self):
        data = embedded(au_plist(0x61756678, SLO_X, vc2(APP_MODEL)))
        self.assertEqual(neural_states(data), [])

    def test_undecodable_juce_state_skipped(self):
        data = embedded(au_plist(NDSP, SLO_X, b"\xde\xad\xbe\xef"))
        self.assertEqual(neural_states(data), [])


class ReadNeuralTest(unittest.TestCase):
    def test_reads_flat_file(self):
        with tempfile.NamedTemporaryFile(suffix=".cst", delete=False) as f:
            f.write(embedded(au_plist(NDSP, SLO_X, vc2(APP_MODEL))))
        try:
            states = read_neural(f.name)
            self.assertEqual(len(states), 1)
            self.assertEqual(states[0]["sections"]["amp"]["ampBass"], 0.71)
        finally:
            os.unlink(f.name)


class CliTest(unittest.TestCase):
    def test_cli_neural_on_synthetic_strip(self):
        from logicxkit.cli import main
        with tempfile.NamedTemporaryFile(suffix=".cst", delete=False) as f:
            f.write(embedded(au_plist(NDSP, SLO_X, vc2(APP_MODEL))))
        try:
            self.assertEqual(main(["logic", "neural", f.name]), 0)
            self.assertEqual(main(["logic", "neural", f.name, "--json"]), 0)
        finally:
            os.unlink(f.name)


if __name__ == "__main__":
    unittest.main()
