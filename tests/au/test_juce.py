"""JUCE state decode: the VC2! XML container, the binary ValueTree, and the
plist-level entry point that picks between them."""

import unittest

from logicxkit.au.services.juce import (
    decode_juce_xml,
    parse_value_tree,
    state_from_plist,
)

from _juce import APP_MODEL, tree, tree_state, var_bin, vc2

SLO_X = 0x4E534C58  # 'NSLX'


class JuceXmlContainerTest(unittest.TestCase):
    def test_unwraps_vc2_container(self):
        self.assertEqual(decode_juce_xml(vc2(APP_MODEL)), APP_MODEL)

    def test_non_vc2_returns_none(self):
        self.assertIsNone(decode_juce_xml(b"neural_dsp_test\x00\x01\x02"))


class ValueTreeTest(unittest.TestCase):
    def test_binary_var_kind8_yields_bytes(self):
        root = parse_value_tree(tree("State", [("Chain", var_bin(b"<Session/>"))]))
        self.assertEqual(root["props"]["Chain"], b"<Session/>")

    def test_parses_props_params_and_nested_trees(self):
        root = parse_value_tree(tree_state())
        self.assertEqual(root["type"], "neural_dsp_test")
        self.assertEqual(root["props"]["tempo"], 210.0)
        self.assertEqual(root["props"]["presetNameProp"], "Default")
        kids = {c["type"] for c in root["children"]}
        self.assertEqual(kids, {"PARAM", "midi_mappings"})

    def test_garbage_returns_none(self):
        self.assertIsNone(parse_value_tree(b"\xff\xfe\x00\x01"))


class StateFromPlistTest(unittest.TestCase):
    def test_xml_container_yields_meta_and_sections(self):
        got = state_from_plist({"subtype": SLO_X, "jucePluginState": vc2(APP_MODEL)})
        self.assertEqual(got["format"], "xml")
        self.assertEqual(got["subtype"], "NSLX")
        self.assertEqual(got["meta"]["presetUid"], 42)
        self.assertEqual(got["sections"]["amp"]["ampBass"], 0.71)
        self.assertIs(got["sections"]["amp"]["ampBright"], True)

    def test_value_tree_yields_params(self):
        got = state_from_plist({"subtype": SLO_X, "jucePluginState": tree_state()})
        self.assertEqual(got["format"], "tree")
        self.assertEqual(got["meta"]["presetNameProp"], "Default")
        self.assertEqual(got["meta"]["plugin_name"], "Soldano SLO-100")
        self.assertEqual(got["sections"]["params"]["ampBass"], 0.71)

    def test_missing_or_undecodable_state_returns_none(self):
        self.assertIsNone(state_from_plist({"subtype": 0}))
        self.assertIsNone(state_from_plist({"subtype": 0, "jucePluginState": "not bytes"}))
        self.assertIsNone(state_from_plist({"subtype": 0, "jucePluginState": b"\xff\xfe"}))

    def test_malformed_xml_in_container_returns_none(self):
        self.assertIsNone(
            state_from_plist({"subtype": 0, "jucePluginState": vc2("<unclosed>")}))


class DeepValueTreeTest(unittest.TestCase):
    def test_nesting_deeper_than_the_stack_returns_none(self):
        self.assertIsNone(parse_value_tree(b"A\x00\x00\x01\x01" * 5000 + b"A\x00\x00\x00"))
