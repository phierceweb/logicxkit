"""Graft tests — splice a target strip's routing header onto a donor's plugin-slot region.

A .cst is [OCuA header | slot region]. The header carries routing (output bus, sends, fader,
channel identity); the slot region carries the plugin chain. Grafting lets us build a chain
shape that no single saved strip has, while keeping a real channel's routing.
"""

import struct
import unittest

from logicxkit.logic import channel_info, graft, seam


def _strip(header_extra: bytes, slots: bytes, chan_word: int = 0x40) -> bytes:
    """Synthetic .cst: OCuA magic, w7=header length, w10=channel word, then slots at w7+0x24."""
    head = bytearray(b"OCuA" + b"\x00" * 60)
    body = b"HDR" + header_extra
    struct.pack_into("<I", head, 28, len(head) + len(body) - 0x24)  # w7
    struct.pack_into("<I", head, 40, chan_word)                      # w10
    return bytes(head) + body + slots


class SeamTest(unittest.TestCase):
    def test_seam_is_w7_plus_0x24(self):
        data = _strip(b"xxxx", b"SLOTS")
        self.assertEqual(seam(data), struct.unpack_from("<I", data, 28)[0] + 0x24)

    def test_seam_splits_header_from_slots(self):
        data = _strip(b"xxxx", b"SLOTS")
        self.assertEqual(data[seam(data):], b"SLOTS")


class ChannelInfoTest(unittest.TestCase):
    def test_track_flag(self):
        info = channel_info(_strip(b"", b"S", chan_word=0xA0040))
        self.assertEqual(info["kind"], "track")
        self.assertEqual(info["number"], 0xA)

    def test_bus_flag(self):
        info = channel_info(_strip(b"", b"S", chan_word=0x70042))
        self.assertEqual(info["kind"], "bus")
        self.assertEqual(info["number"], 0x7)

    def test_all_known_kinds(self):
        for flag, kind in ((0x40, "track"), (0x42, "bus"), (0x43, "instrument"), (0x4C, "output")):
            self.assertEqual(channel_info(_strip(b"", b"S", chan_word=flag))["kind"], kind)

    def test_unknown_flag_is_reported_not_raised(self):
        self.assertEqual(channel_info(_strip(b"", b"S", chan_word=0x99))["kind"], "unknown")


class GraftTest(unittest.TestCase):
    def setUp(self):
        self.target = _strip(b"TARGETROUTING", b"TARGET-SLOTS", chan_word=0x80040)
        self.donor = _strip(b"DONORROUTING!!!!!", b"DONOR-SLOTS-LONGER", chan_word=0x20042)

    def test_takes_target_header_and_donor_slots(self):
        out = graft(self.target, self.donor)
        self.assertEqual(out[:seam(self.target)], self.target[:seam(self.target)])
        self.assertEqual(out[seam(out):], b"DONOR-SLOTS-LONGER")

    def test_preserves_target_channel_identity(self):
        out = graft(self.target, self.donor)
        self.assertEqual(channel_info(out), channel_info(self.target))

    def test_seam_still_valid_after_graft(self):
        """The grafted file's own w7 must still locate the boundary (header is unmodified)."""
        out = graft(self.target, self.donor)
        self.assertEqual(seam(out), seam(self.target))

    def test_rejects_non_ocua(self):
        with self.assertRaises(ValueError):
            graft(b"NOPE" + b"\x00" * 80, self.donor)

    def test_rejects_truncated(self):
        with self.assertRaises(ValueError):
            graft(b"OCuA", self.donor)


class PresetLabelTest(unittest.TestCase):
    """Slot preset labels ("<name>.pst") live in fixed 67-byte null-padded fields, so they can be
    rewritten in place. A graft otherwise inherits the donor's labels, which then misdescribe it."""

    FIELD = 67

    def _with_label(self, name: str) -> bytes:
        field = name.encode() + b"\x00" * (self.FIELD - len(name))
        return _strip(b"", b"\x12\x35\x00" + field + b"\x01\x01\x01\x01" + b"SLOTS")

    def test_reads_label(self):
        from logicxkit.logic import preset_labels
        self.assertEqual([n for _, n in preset_labels(self._with_label("Clean Up Snare.pst"))],
                         ["Clean Up Snare.pst"])

    def test_rewrite_preserves_length(self):
        from logicxkit.logic import relabel_presets
        data = self._with_label("Clean Up Snare.pst")
        out = relabel_presets(data, "Vox Tracking")
        self.assertEqual(len(out), len(data))

    def test_rewrite_sets_name_and_nulls_the_rest(self):
        from logicxkit.logic import preset_labels, relabel_presets
        data = self._with_label("Clean Up Snare.pst")
        out = relabel_presets(data, "Vox Tracking")
        self.assertEqual([n for _, n in preset_labels(out)], ["Vox Tracking.pst"])
        off = preset_labels(out)[0][0]
        self.assertEqual(out[off + len("Vox Tracking.pst"):off + self.FIELD],
                         b"\x00" * (self.FIELD - len("Vox Tracking.pst")))

    def test_shorter_name_leaves_no_stale_tail(self):
        """Overwriting a long label with a short one must not leave the old suffix readable."""
        from logicxkit.logic import relabel_presets
        out = relabel_presets(self._with_label("A Very Long Preset Name Indeed.pst"), "Short")
        self.assertNotIn(b"Indeed", out)

    def test_rejects_overlong_name(self):
        from logicxkit.logic import relabel_presets
        with self.assertRaises(ValueError):
            relabel_presets(self._with_label("X.pst"), "y" * 80)


class SpecGraftTest(unittest.TestCase):
    """A preset may source its base bytes from a `template`, or from a `graft` pair
    (routing_from + chain_from). `assemble` is the single entry point build/verify share."""

    def setUp(self):
        self.routing = _strip(b"ROUTING", b"\x00" + b"OLD.pst".ljust(67, b"\x00") + b"R-SLOTS",
                              chan_word=0x50040)
        self.donor = _strip(b"DONOR", b"\x00" + b"DON.pst".ljust(67, b"\x00") + b"D-SLOTS",
                            chan_word=0x10042)
        self.files = {"/r.cst": self.routing, "/d.cst": self.donor}
        self.load = lambda p: self.files[str(p)]

    def _assemble(self, preset, spec=None):
        from logicxkit.logic import assemble
        return assemble(spec or {}, preset, self.load)

    def test_template_path_still_works(self):
        out = self._assemble({}, {"template": "/r.cst"})
        self.assertEqual(out, self.routing)

    def test_graft_takes_routing_header_and_donor_chain(self):
        out = self._assemble({"graft": {"routing_from": "/r.cst", "chain_from": "/d.cst"}})
        self.assertEqual(channel_info(out), channel_info(self.routing))
        self.assertTrue(out.endswith(b"D-SLOTS"))

    def test_label_rewrites_inherited_donor_label(self):
        from logicxkit.logic import preset_labels
        out = self._assemble({"graft": {"routing_from": "/r.cst", "chain_from": "/d.cst"},
                              "label": "Vox Tracking"})
        self.assertEqual([n for _, n in preset_labels(out)], ["Vox Tracking.pst"])

    def test_graft_missing_key_raises(self):
        with self.assertRaises(ValueError):
            self._assemble({"graft": {"routing_from": "/r.cst"}})

    def test_graft_and_template_together_raises(self):
        """Ambiguous base — refuse rather than silently preferring one."""
        with self.assertRaises(ValueError):
            self._assemble({"template": "/r.cst",
                            "graft": {"routing_from": "/r.cst", "chain_from": "/d.cst"}})


class IdentifyPluginTest(unittest.TestCase):
    """Native plugins are identified from the ASCII name preceding their GAMETSPP block.
    Matching must be token-anchored: a bare substring test makes 'Gain' match 'Auto Gain'."""

    def _ctx(self, label: str) -> tuple[bytes, int]:
        """Name, null padding, then the real 12-byte chunk pre-header, then the tag."""
        data = (b"\x00" + label.encode() + b"\x00" * 8
                + struct.pack("<III", 24 + 4 * 4, 1, 4) + b"GAMETSPP" + b"\x00" * 20)
        return data, data.index(b"GAMETSPP")

    def test_identifies_gain(self):
        from logicxkit.logic import identify_plugin
        d, i = self._ctx("Gain")
        self.assertEqual(identify_plugin(d, i), "Gain")

    def test_identifies_limiter(self):
        from logicxkit.logic import identify_plugin
        d, i = self._ctx("Limiter")
        self.assertEqual(identify_plugin(d, i), "Limiter")

    def test_adaptive_limiter_not_confused_with_limiter(self):
        from logicxkit.logic import identify_plugin
        d, i = self._ctx("Adaptive Limiter")
        self.assertEqual(identify_plugin(d, i), "Adaptive Limiter")

    def test_auto_gain_does_not_match_gain(self):
        """A compressor's 'Auto Gain' parameter text must not identify the block as Gain."""
        from logicxkit.logic import identify_plugin
        d, i = self._ctx("Auto Gain")
        self.assertNotEqual(identify_plugin(d, i), "Gain")

    def test_known_plugins_still_identified(self):
        from logicxkit.logic import identify_plugin
        for label, want in (("ChanEQ", "Channel EQ"), ("Compressor", "Compressor"),
                            ("Enveloper", "Enveloper")):
            d, i = self._ctx(label)
            self.assertEqual(identify_plugin(d, i), want)


class ProvenanceTest(unittest.TestCase):
    """Every strip records its own filename + folder in a UCuA record (name at tag+52, then
    category, each a 64-byte null-padded field). A clone or graft inherits the DONOR's,
    so the built strip claims to be a different file — which misleads Logic's Setting
    display and `logic diff --library`. Rewriting is in-place and length-preserving."""

    FIELD = 64

    def _strip_with(self, name: str, category: str) -> bytes:
        rec = (b"UCuA" + b"\x00" * 48
               + name.encode().ljust(self.FIELD, b"\x00")
               + category.encode().ljust(self.FIELD, b"\x00"))
        return _strip(b"", b"\x00" + rec + b"TAIL")

    def test_reads_provenance(self):
        from logicxkit.logic import provenance
        data = self._strip_with("OH L.cst", "Tracking")
        self.assertEqual(provenance(data)[0][1:], ("OH L.cst", "Tracking"))

    def test_rewrite_is_length_preserving(self):
        from logicxkit.logic import set_provenance
        data = self._strip_with("OH L.cst", "Tracking")
        out = set_provenance(data, "Vox Tracking.cst", "Tracking Rec")
        self.assertEqual(len(out), len(data))

    def test_rewrite_sets_both_fields(self):
        from logicxkit.logic import provenance, set_provenance
        out = set_provenance(self._strip_with("OH L.cst", "Tracking"),
                             "Vox Tracking.cst", "Vocals")
        self.assertEqual(provenance(out)[0][1:], ("Vox Tracking.cst", "Vocals"))

    def test_longer_name_leaves_no_stale_tail(self):
        from logicxkit.logic import set_provenance
        out = set_provenance(self._strip_with("A Really Long Donor Name.cst", "Cat"),
                             "Short.cst", "C")
        self.assertNotIn(b"Donor", out)

    def test_rejects_overlong(self):
        from logicxkit.logic import set_provenance
        with self.assertRaises(ValueError):
            set_provenance(self._strip_with("A.cst", "C"), "x" * 70 + ".cst", "C")
