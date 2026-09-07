"""Waves_XPst chunks: binary head + PresetChunkXMLTree XML with RealWorld values."""
import unittest

from logicxkit.au.services.waves import extract_xpst

XML = """<PresetChunkXMLTree version="2">
  <Preset Name="" GenericType="FAZE">
    <PresetHeader>
      <PluginName>InPhase</PluginName>
      <PluginVersion>10.0.55</PluginVersion>
      <ActiveSetup>SETUP_A</ActiveSetup>
    </PresetHeader>
    <PresetData Setup="SETUP_A">
      <Parameters Type="RealWorld">0 1.5 * -3.92
2000 *</Parameters>
    </PresetData>
    <PresetData Setup="SETUP_B">
      <Parameters Type="RealWorld">1 2 3</Parameters>
    </PresetData>
  </Preset>
</PresetChunkXMLTree>"""


class TestExtractXpst(unittest.TestCase):
    def test_extracts_plugin_and_realworld_values(self):
        chunk = b"\x01\x00\x00\x00\x00\x00\x00\x00PHZMsetA\x00\x00\x01\x00XPst" + XML.encode()
        x = extract_xpst(chunk)
        self.assertEqual(x["plugin"], "InPhase")
        self.assertEqual(x["active_setup"], "SETUP_A")
        self.assertEqual(x["setups"]["SETUP_A"], [0.0, 1.5, None, -3.92, 2000.0, None])
        self.assertEqual(x["setups"]["SETUP_B"], [1.0, 2.0, 3.0])

    def test_garbage_returns_none(self):
        self.assertIsNone(extract_xpst(b"not a waves chunk at all"))

    def test_truncated_xml_returns_none(self):
        chunk = b"headXPst<PresetChunkXMLTree version='2'><Preset"
        self.assertIsNone(extract_xpst(chunk))


if __name__ == "__main__":
    unittest.main()
