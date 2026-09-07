"""Logic project analyzer tests — channel-chain + preset + track-name extraction.

Synthetic ``ProjectData`` bytes: a channel is an ``OCuA <ver> 00 0e 00`` header (version
word 06 or 07 by Logic build), a `` Audio N`` label, padding past the 260-byte slot window,
then ``.CuA``-tagged insert slots each carrying a preset filename + plugin name."""

import struct
import tempfile
import unittest
from pathlib import Path
from logicxkit.logicx import channel_label
from logicxkit.logic.services.project import (
    analyze,
    channel_chain,
    channel_cst_refs,
    channel_natives,
    strip_chain,
    track_names,
    window_image_path,
)


def _slot(plugin: str, preset: str | None) -> bytes:
    # real files separate the tag / preset / plugin-name tokens with binary bytes, so each
    # printable run is isolated (a preset regex must not swallow the "UCuA" tag).
    s = b"UCuA\x00\x00"
    if preset:
        s += preset.encode("latin-1") + b".aupreset\x00\x00"
    return s + plugin.encode("latin-1") + b"\x00\x00"


def _labeled_channel(label: str, slots, extra: bytes = b"", ver: int = 6) -> bytes:
    # label within first 160 bytes; first slot pushed past the 260-byte slot window so the
    # OCuA header itself isn't read as a plugin slot (mirrors real channel spacing).
    hdr = (b"OCuA" + bytes((ver,)) + b"\x00\x0e\x00" + b"\x00" * 24 + f" {label}\x00".encode()
           + extra + b"\x00" * 240)
    return hdr + b"".join(_slot(p, pre) for p, pre in slots)


def _channel(n: int, slots) -> bytes:
    return _labeled_channel(f"Audio {n}", slots)


def _gametspp(label: str, floats) -> bytes:
    body = struct.pack("<I", len(floats) * 4) + struct.pack(f"<{len(floats)}f", *floats)
    return (label + " ").encode("latin-1") + b"GAMETSPP" + body


class ChannelChainTest(unittest.TestCase):
    def test_chain_order_and_presets(self):
        seg = _channel(4, [("Neutron 5", None), ("Pro-Q 4", "Snare - TOP 02"), ("Pro-C 2", None)])
        self.assertEqual(
            channel_chain(seg),
            [("Neutron 5", None), ("Pro-Q 4", "Snare - TOP 02"), ("Pro-C 2", None)],
        )

    def test_generic_preset_names_dropped(self):
        seg = _channel(2, [("Pro-C 2", "Default Setting")])
        self.assertEqual(channel_chain(seg), [("Pro-C 2", None)])

    def test_oh_preset_attribution(self):
        seg = _channel(21, [("InPhase", None), ("Pro-C 2", None), ("Pro-Q 4", "Vocal Lead 3")])
        self.assertEqual(channel_chain(seg)[-1], ("Pro-Q 4", "Vocal Lead 3"))


class AnalyzeTest(unittest.TestCase):
    def setUp(self):
        self.data = (
            _channel(4, [("Neutron 5", None), ("Pro-Q 4", "Snare - TOP 02"), ("Pro-C 2", None)])
            + b"\x00" * 16
            + _channel(21, [("InPhase", None), ("Pro-C 2", None), ("Pro-Q 4", "Vocal Lead 3")])
            + b"Kick In: Kick In.4\x00"
            + b"OH L: OH L.2\x00"
        )

    def test_lists_channels_with_inserts(self):
        chans = {c["label"]: c["chain"] for c in analyze(self.data)["channels"]}
        self.assertEqual(set(chans), {"Audio 4", "Audio 21"})
        self.assertEqual(chans["Audio 4"][1], ("Pro-Q 4", "Snare - TOP 02"))

    def test_track_name_table(self):
        names = dict(track_names(self.data))
        self.assertEqual(names, {"Kick In": "4", "OH L": "2"})

    def test_empty_channels_skipped(self):
        # a header with no insert slots must not appear in the inventory
        data = _channel(9, []) + self.data
        labels = {c["label"] for c in analyze(data)["channels"]}
        self.assertNotIn("Audio 9", labels)


class ChannelHeaderVersionTest(unittest.TestCase):
    """Logic re-saves since 2026-06 write channel-object version 07 (was 06) — both
    generations must parse (the Recording template is v7, the Mix template v6)."""

    def test_v7_header_channel_found(self):
        data = _labeled_channel("Audio 1", [("Compressor", None)], ver=7)
        labels = {c["label"] for c in analyze(data)["channels"]}
        self.assertIn("Audio 1", labels)

    def test_v7_cst_ref_attributed(self):
        data = _labeled_channel("Audio 1", [], extra=b"\x00Kick In.cst\x00", ver=7)
        chans = analyze(data)["channels"]
        self.assertEqual(chans[0]["cst"], ["Kick In.cst"])


class ChannelLabelTest(unittest.TestCase):
    """Every strip type carries a label string (probe 2026-06-12): Audio/Input/Aux/
    Inst/Output/Bus/Master — not just ' Audio N'."""

    def test_bus_and_other_type_labels(self):
        for label in ("Bus 5", "Input 12", "Aux 1", "Inst 1", "Output 3", "Master"):
            seg = _labeled_channel(label, [])
            self.assertEqual(channel_label(seg), label)

    def test_unlabelled_block_stays_unknown(self):
        seg = b"OCuA\x06\x00\x0e\x00" + b"\x00" * 200
        self.assertEqual(channel_label(seg), "?")


class CstRefTest(unittest.TestCase):
    def test_refs_extracted_and_deduped(self):
        seg = _labeled_channel("Audio 1", [("Compressor", None)],
                               extra=b"\x00Kick In.cst\x00\x07Kick In.cst\x00")
        self.assertEqual(channel_cst_refs(seg), ["Kick In.cst"])

    def test_no_refs_is_empty(self):
        self.assertEqual(channel_cst_refs(_channel(2, [("Pro-Q 4", None)])), [])

    def test_analyze_carries_cst_field(self):
        data = _labeled_channel("Audio 1", [("Compressor", None)],
                                extra=b"\x00Kick In.cst\x00")
        chans = analyze(data)["channels"]
        self.assertEqual(chans[0]["cst"], ["Kick In.cst"])


class StripChainTest(unittest.TestCase):
    def test_chain_of_a_standalone_strip(self):
        cst = _labeled_channel("Audio 1", [("Channel EQ", None), ("Compressor", None)])
        self.assertEqual(strip_chain(cst),
                         [("Channel EQ", None), ("Compressor", None)])


class WindowImageTest(unittest.TestCase):
    def test_returns_first_alternative_image(self):
        with tempfile.TemporaryDirectory() as d:
            alt = Path(d, "X.logicx", "Alternatives", "000")
            alt.mkdir(parents=True)
            (alt / "WindowImage.jpg").write_bytes(b"\xff\xd8jpeg")
            p = window_image_path(Path(d, "X.logicx"))
            self.assertEqual(p.read_bytes(), b"\xff\xd8jpeg")

    def test_missing_image_raises(self):
        with tempfile.TemporaryDirectory() as d:
            alt = Path(d, "X.logicx", "Alternatives", "000")
            alt.mkdir(parents=True)
            with self.assertRaises(FileNotFoundError):
                window_image_path(Path(d, "X.logicx"))


class NativeParamsTest(unittest.TestCase):
    def test_decodes_native_compressor_in_channel(self):
        comp = _gametspp(
            "Compressor",
            [0.0, -20.0, 3.0, 15.0, 75.0, 4.0, 0.5, 0.7, 0.0, 0.0, 6.0, 0.0, 0.0, 0.0],
        )
        seg = _channel(5, [("Compressor", None)]) + comp
        natives = channel_natives(seg)
        self.assertEqual(natives[0][0], "Compressor")
        self.assertEqual(natives[0][1]["circuit"], "StudioFET")
        self.assertEqual(natives[0][1]["threshold"], -20.0)


if __name__ == "__main__":
    unittest.main()
