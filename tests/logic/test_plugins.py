"""Which plug-ins a project references, and whether this Mac has them: Apple's own are named
by type id; a third-party slot carries its AU component identity in an embedded preset plist."""

import plistlib
import struct
import unittest
import _paths  # noqa: F401
from logicxkit.logic.services.mixer.plugins import (
    PluginRef, installed_from_auval, is_instrument_plugin, project_plugins, validate_components, verdict,
)

HDR = 36


def rec(tag: bytes, owner: int, key: int, payload: bytes, ver: int = 5) -> bytes:
    h = bytearray(HDR)
    h[0:4] = tag
    struct.pack_into("<H", h, 4, ver)
    struct.pack_into("<H", h, 14, owner)
    struct.pack_into("<H", h, 18, key)
    struct.pack_into("<I", h, 28, len(payload))
    return bytes(h) + payload


def native_slot(owner: int, key: int, type_id: int, n: int = 8) -> bytes:
    p = bytearray(220)
    p[184:192] = b"GAMETSPP"
    struct.pack_into("<III", p, 172, 24 + n * 4, 1, n)
    struct.pack_into("<I", p, 192, type_id)
    return rec(b"UCuA", owner, key, bytes(p))


def fourcc(s: str) -> int:
    return struct.unpack(">I", s.encode("latin-1"))[0]


def third_party_slot(owner: int, key: int, *, type_="aufx", subtype="FC2p", manu="FabF", name="Pro-C 2") -> bytes:
    pl = plistlib.dumps({"type": fourcc(type_), "subtype": fourcc(subtype), "manufacturer": fourcc(manu),
                         "name": name, "version": 0, "data": b"\0" * 12}, fmt=plistlib.FMT_XML)
    return rec(b"UCuA", owner, key, bytes(64) + pl + bytes(16))


def headed_slot(owner: int, key: int, name: bytes, maker: bytes, word: int, code: bytes, *, flags: int = 0,
                state: bytes = b"") -> bytes:
    """A slot with Logic's header (kind word 1, the short name, the three identity words) and any state."""
    p = bytearray(176)
    struct.pack_into("<H", p, 4, 1)
    p[120:120 + len(name)] = name
    p[132:136], p[140:144] = maker, code
    struct.pack_into("<I", p, 136, word)
    p[151] = flags
    return rec(b"UCuA", owner, key, bytes(p) + state)


def float_block(type_id: int, n: int = 8) -> bytes:
    return struct.pack("<II", 1, n) + b"GAMETSPP" + struct.pack("<I", type_id) + bytes(n * 4)


def chan(owner: int, label: str) -> bytes:
    p = bytearray(257)
    p[24] = p[25] = 1
    p[60:60 + len(label) + 1] = b" " + label.encode()
    return rec(b"OCuA", owner, 0xFFFF, bytes(p), 7)


def proj(*records: bytes) -> bytes:
    body = b"".join(records)
    head = bytearray(24)
    struct.pack_into("<I", head, 0x10, len(body))
    return bytes(head) + body


class ProjectPluginsTest(unittest.TestCase):
    def test_native_and_third_party_slots_are_identified(self):
        data = proj(chan(0, "Audio 1"), native_slot(0, 2, 236), third_party_slot(0, 3), chan(1, "Audio 2"))
        refs = project_plugins(data)
        self.assertEqual([(r.channel, r.key, r.name, r.native, r.component) for r in refs],
                         [("Audio 1", 2, "Channel EQ", True, None),
                          ("Audio 1", 3, "FabF/FC2p", False, ("aufx", "FC2p", "FabF"))])


class HeaderNamedSlotsTest(unittest.TestCase):
    def names(self, *slots: bytes) -> list[tuple]:
        return [(r.key, r.name, r.native, r.component) for r in project_plugins(proj(chan(0, "Inst 1"), *slots))]

    def test_a_sampler_family_instrument_with_no_float_block_is_listed(self):
        slot = headed_slot(0, 2, b"Drum Kit", b"MELC", 0, b"LMNA", flags=8, state=b"MELCPMASLMNA" + bytes(40))
        self.assertEqual(self.names(slot), [(2, "Drum Kit Designer", True, None)])

    def test_a_slot_with_no_state_is_listed_by_its_type_id(self):
        slot = headed_slot(0, 4, b"Remix FX", b"GAME", 0, struct.pack("<I", 314))
        self.assertEqual(self.names(slot), [(4, "Remix FX", True, None)])

    def test_the_header_names_a_slot_whose_state_holds_another_types_block(self):
        slot = headed_slot(0, 2, b"Piano", b"MELC", 4, b"rWnI", flags=8, state=bytes(64) + float_block(312))
        self.assertEqual(self.names(slot), [(2, "Studio Piano", True, None)])

    def test_a_slot_of_logics_own_that_no_table_names_takes_the_headers_short_name(self):
        native = headed_slot(0, 3, b"Later Synth", b"GAME", 0, struct.pack("<I", 9999), state=float_block(9999))
        family = headed_slot(0, 4, b"Later Kit", b"MELC", 0, b"ZZZZ")
        self.assertEqual(self.names(native, family), [(3, "Later Synth", True, None), (4, "Later Kit", True, None)])

    def test_a_shared_type_is_still_told_apart_by_its_variant_base(self):
        slot = bytearray(headed_slot(0, 2, b"Echo", b"GAME", 33, struct.pack("<I", 147), state=float_block(147)))
        struct.pack_into("<H", slot, HDR + 116, 216 + 1)
        slot[HDR + 81] = 1
        self.assertEqual(self.names(bytes(slot)), [(2, "Echo", True, None)])

    def test_a_pedalboard_stompbox_is_named_by_its_variant_base(self):
        """Pedalboard's 35 pedals share its type 273; each has a variant base of its own."""
        from logicxkit.logic.services.mixer.plugin_names import PLUGIN_VARIANTS, native_name
        self.assertEqual(len(PLUGIN_VARIANTS[273]), 36)
        self.assertEqual((native_name(273, 1623), native_name(273, 1739), native_name(273, 1755)),
                         ("Pedalboard", "Auto-Funk", "Blue Echo"))
        slot = bytearray(headed_slot(0, 2, b"Auto-Funk", b"GAME", 7, struct.pack("<I", 273), state=float_block(273)))
        struct.pack_into("<H", slot, HDR + 116, 1739 + 1)
        slot[HDR + 81] = 1
        self.assertEqual(self.names(bytes(slot)), [(2, "Auto-Funk", True, None)])


class MidiEffectSlotTest(unittest.TestCase):
    def test_a_midi_effect_is_listed_and_marked(self):
        arp = bytearray(headed_slot(0, 4, b"Arpeggiator", b"GAME", 0, struct.pack("<I", 300), flags=0x02, state=float_block(300)))
        struct.pack_into("<H", arp, HDR + 4, 2)
        eq = headed_slot(0, 3, b"Channel EQ", b"GAME", 0, struct.pack("<I", 236), state=float_block(236))
        refs = project_plugins(proj(chan(0, "Inst 1"), eq, bytes(arp)))
        self.assertEqual([(r.key, r.name, r.native, r.midi) for r in refs],
                         [(3, "Channel EQ", True, False), (4, "Arpeggiator", True, True)])


class InstrumentSlotTest(unittest.TestCase):
    def test_the_header_flag_says_a_slot_holds_the_channels_instrument(self):
        kit = headed_slot(0, 2, b"Drum Kit", b"MELC", 0, b"LMNA", flags=0x08)
        synth = headed_slot(0, 2, b"ES2", b"GAME", 0, struct.pack("<I", 214), flags=0x18, state=float_block(214))
        self.assertTrue(is_instrument_plugin(kit[HDR:]))
        self.assertTrue(is_instrument_plugin(synth[HDR:]))

    def test_an_effect_whose_window_has_been_open_is_not_an_instrument(self):
        eq = headed_slot(0, 3, b"Channel EQ", b"GAME", 0, struct.pack("<I", 236), flags=0x10, state=float_block(236))
        self.assertFalse(is_instrument_plugin(eq[HDR:]))

    def test_a_block_with_no_slot_header_is_judged_by_its_type(self):
        self.assertTrue(is_instrument_plugin(native_slot(0, 2, 158)[HDR:]))
        self.assertFalse(is_instrument_plugin(native_slot(0, 2, 236)[HDR:]))


class VerdictTest(unittest.TestCase):
    REFS = [PluginRef("Audio 1", 2, "Channel EQ", True, None),
            PluginRef("Audio 1", 3, "Pro-C 2", False, ("aufx", "FC2p", "FabF")),
            PluginRef("Audio 2", 2, "Gone", False, ("aufx", "Xxxx", "Nono"))]

    def test_missing_third_party_components_are_named(self):
        v = verdict(self.REFS, installed={("aufx", "FC2p", "FabF")})
        self.assertEqual([(r.name, s) for r, s in v.slots], [("Channel EQ", "apple"), ("Pro-C 2", "installed"), ("Gone", "missing")])
        self.assertEqual((v.missing, v.clean), ([self.REFS[2]], False))

    def test_a_project_with_every_component_present_is_clean(self):
        v = verdict(self.REFS[:2], installed={("aufx", "FC2p", "FabF")})
        self.assertTrue(v.clean)

    def test_a_listed_component_that_fails_to_open_is_broken_and_counts_as_missing(self):
        """The registry kept FabFilter Pro-C 2 listed while its bundle was disabled, and Logic opened
        the project with no alert; only `auval -v` failed."""
        v = verdict(self.REFS[:2], installed={("aufx", "FC2p", "FabF")}, validated={("aufx", "FC2p", "FabF"): False})
        self.assertEqual([s for _r, s in v.slots], ["apple", "broken"])
        self.assertEqual((v.missing, v.clean), ([self.REFS[1]], False))

    def test_validation_reads_pass_and_fatal_errors_from_auval(self):
        import subprocess
        from unittest import mock
        runs = {("aufx", "FC2p", "FabF"): (0, "* * PASS\n"), ("aufx", "Xxxx", "Nono"): (255, "FATAL ERROR: OpenAComponent: result: -1\n")}

        def fake_run(argv, **_k):
            code, out = runs[tuple(argv[2:5])]
            return subprocess.CompletedProcess(argv, code, out, "")
        with mock.patch("logicxkit.logic.services.mixer.plugins.shutil.which", return_value="/usr/bin/auval"), \
             mock.patch("logicxkit.logic.services.mixer.plugins.subprocess.run", side_effect=fake_run):
            self.assertEqual(validate_components(set(runs)), {("aufx", "FC2p", "FabF"): True, ("aufx", "Xxxx", "Nono"): False})

    def test_a_registry_scan_that_hangs_reads_as_unknown_not_clean(self):
        import subprocess
        from unittest import mock
        from logicxkit.logic.services.mixer.plugins import installed_components
        with mock.patch("logicxkit.logic.services.mixer.plugins.shutil.which", return_value="/usr/bin/auval"), \
             mock.patch("logicxkit.logic.services.mixer.plugins.subprocess.run",
                        side_effect=subprocess.TimeoutExpired(["auval", "-a"], 1)):
            self.assertIsNone(installed_components(timeout=1))
        v = verdict(self.REFS[:2], installed=None)
        self.assertEqual([s for _r, s in v.slots], ["apple", "unknown"])

    def test_a_component_that_hangs_is_broken_and_the_others_are_still_reported(self):
        import subprocess
        from unittest import mock
        seen = []

        def fake_run(argv, **kw):
            comp = tuple(argv[2:5])
            if comp == ("aufx", "Hang", "Hung"):
                raise subprocess.TimeoutExpired(argv, kw.get("timeout"))
            return subprocess.CompletedProcess(argv, 0, "* * PASS\n", "")
        with mock.patch("logicxkit.logic.services.mixer.plugins.shutil.which", return_value="/usr/bin/auval"), \
             mock.patch("logicxkit.logic.services.mixer.plugins.subprocess.run", side_effect=fake_run):
            got = validate_components({("aufx", "Hang", "Hung"), ("aufx", "Fine", "Good")}, progress=seen.append)
        self.assertEqual(got, {("aufx", "Hang", "Hung"): False, ("aufx", "Fine", "Good"): True})
        self.assertEqual(seen, [("aufx", "Fine", "Good"), ("aufx", "Hang", "Hung")])

    def test_a_failed_validation_is_read_from_its_markers_not_pass_lines(self):
        import subprocess
        from unittest import mock
        text = "* * PASS\n* * PASS\nAU VALIDATION FAILED\n"
        with mock.patch("logicxkit.logic.services.mixer.plugins.shutil.which", return_value="/usr/bin/auval"), \
             mock.patch("logicxkit.logic.services.mixer.plugins.subprocess.run",
                        return_value=subprocess.CompletedProcess([], 0, text, "")):
            self.assertEqual(validate_components({("aufx", "Xxxx", "Nono")}), {("aufx", "Xxxx", "Nono"): False})
        with mock.patch("logicxkit.logic.services.mixer.plugins.shutil.which", return_value=None):
            self.assertEqual(validate_components({("aufx", "Xxxx", "Nono")}), {})
        with mock.patch("logicxkit.logic.services.mixer.plugins.shutil.which", return_value="/usr/bin/auval"), \
             mock.patch("logicxkit.logic.services.mixer.plugins.subprocess.run",
                        return_value=subprocess.CompletedProcess([], 0, "", "")):
            self.assertEqual(validate_components({("aufx", "Xxxx", "Nono")}), {("aufx", "Xxxx", "Nono"): False},
                             "a clean exit that ran no test is not a pass")


class AuvalTest(unittest.TestCase):
    def test_the_installed_set_comes_from_auval_lines(self):
        text = ("    AU Validation Tool\n    Version: 1.10.0\n\n"
                "aufx Aln2 Srdx  -  Sound Radix: Auto-Align 2\n"
                "aumu Nave Wald  -  Waldorf: Nave\n")
        self.assertEqual(installed_from_auval(text), {("aufx", "Aln2", "Srdx"), ("aumu", "Nave", "Wald")})


if __name__ == "__main__":
    unittest.main()
