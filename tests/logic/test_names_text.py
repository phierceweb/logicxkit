"""Names outside ASCII in the records beside the track's: a text record (sections, markers) plain
as UTF-8 or as the RTF Logic's own rename writes, and a group's name as UTF-8 by byte length."""

import struct
import unittest

import _paths  # noqa: F401
from logicxkit.logic.services.song.arrangement import TEXT_NAME_AT, _text
from logicxkit.logic.services.song.arrangement_write import plain_text_payload
from logicxkit.logic.services.arrange.groups import NAME_AT, _name_of, _with_name
from logicxkit.logic.services.arrange.names import written
from logicxkit.logic.services.song.rtf import rtf_text

HEAD = (b"{\\rtf1\\ansi\\ansicpg1252\\cocoartf2870\n\\cocoatextscaling0\\cocoaplatform0"
        b"{\\fonttbl\\f0\\fnil\\fcharset0 HelveticaNeue;}\n{\\colortbl;\\red255\\green255\\blue255;}\n"
        b"{\\*\\expandedcolortbl;;\\cssrgb\\c100000\\c100000\\c100000\\c67000;}\n"
        b"\\pard\\tx560\\tx1120\\pardirnatural\\partightenfactor0\n\n\\f0\\fs24 \\cf2 ")


def rtf(body: bytes) -> bytes:
    return HEAD + body + b"}"


class RtfTest(unittest.TestCase):
    def test_a_plain_run_reads_as_before(self):
        self.assertEqual(rtf_text(rtf(b"Chorus")), "Chorus")

    def test_hex_escapes_are_cp1252_and_u_escapes_utf16_units(self):
        self.assertEqual(rtf_text(rtf(b"Cora\\'e7\\'e3o \\'f1 \\uc0\\u55356 \\u57274 ")), "Coração ñ 🎺")
        self.assertEqual(rtf_text(rtf(b"\\'dcbergang \\uc0\\u9837  \\u55356 \\u57273 ")), "Übergang ♭ 🎹")

    def test_a_negative_u_escape_and_escaped_punctuation(self):
        self.assertEqual(rtf_text(rtf(b"a\\uc0\\u-10180 \\u-8263 b \\{x\\} \\\\")), "a🎹b {x} \\")

    def test_later_runs_and_control_words_inside_the_text_are_followed(self):
        self.assertEqual(rtf_text(rtf(b"Pre \\cf3 \\b Chorus\\b0")), "Pre Chorus")

    def test_a_line_break_keeps_its_place(self):
        self.assertEqual(rtf_text(rtf(b"Verse\\\nsecond line")), "Verse\nsecond line")

    def test_bytes_after_the_documents_closing_brace_are_not_text(self):
        self.assertEqual(rtf_text(rtf(b"Pre Chorus") + b"\x86"), "Pre Chorus")

    def test_text_with_no_colour_run_reads_from_the_paragraph(self):
        self.assertEqual(rtf_text(b"{\\rtf1\\ansi{\\fonttbl\\f0 Helvetica;}\\pard\\f0\\fs24 Bridge}"), "Bridge")


class TextRecordTest(unittest.TestCase):
    def test_a_plain_record_reads_as_utf8(self):
        self.assertEqual(_text(bytes(TEXT_NAME_AT) + "Brücke 🎸".encode() + b"\0\0"), "Brücke 🎸")

    def test_bytes_that_are_not_utf8_still_read(self):
        self.assertEqual(_text(bytes(TEXT_NAME_AT) + b"Br\xfccke\0"), "Brücke")

    def test_an_rtf_record_reads_its_escapes(self):
        self.assertEqual(_text(bytes(TEXT_NAME_AT) + rtf(b"\\'dcbergang") + b"\0"), "Übergang")

    def test_a_written_name_is_utf8_with_its_nul_padded_even(self):
        p = plain_text_payload("Refrão é")
        self.assertEqual(p[TEXT_NAME_AT:], "Refrão é".encode() + b"\0\0")
        self.assertEqual(struct.unpack_from("<I", p, 0)[0], len(p))
        self.assertEqual(_text(p), "Refrão é")


class GroupNameTest(unittest.TestCase):
    def payload(self, name: bytes) -> bytes:
        return bytes(NAME_AT) + struct.pack("<H", len(name)) + name + b"\0" * (len(name) % 2) + b"TAIL"

    def test_the_name_is_utf8_by_byte_length(self):
        out = _with_name(self.payload(b"Drums"), "Bläser ü")
        encoded = "Bläser ü".encode()
        self.assertEqual(struct.unpack_from("<H", out, NAME_AT)[0], len(encoded))
        self.assertEqual(out[NAME_AT + 2:], encoded + b"TAIL")
        self.assertEqual(_name_of(out), "Bläser ü")

    def test_an_odd_length_is_padded_and_the_rest_keeps_its_place(self):
        out = _with_name(self.payload(b"Drums"), "Größe")
        self.assertEqual(out[NAME_AT + 2:], "Größe".encode() + b"\0TAIL")

    def test_63_bytes_is_the_limit_and_an_empty_name_stays_allowed(self):
        self.assertEqual(_name_of(_with_name(self.payload(b"Drums"), "")), "")
        _with_name(self.payload(b"Drums"), "ü" * 31 + "a")
        with self.assertRaises(ValueError):
            _with_name(self.payload(b"Drums"), "ü" * 32)


class WrittenNameTest(unittest.TestCase):
    def test_control_characters_line_separators_and_direction_controls_are_refused(self):
        for bad in ("a\x07b", "a b", "‮evil", "a\x85b", "​"):
            with self.subTest(repr(bad)), self.assertRaises(ValueError):
                written(bad, "a section name")

    def test_a_name_of_blank_letters_is_refused_and_a_name_with_one_passes(self):
        for blank in ("\u3164", "\u2800\u2800", "\u115f\u1160", "\uffa0 "):
            with self.subTest(repr(blank)), self.assertRaisesRegex(ValueError, "visible character"):
                written(blank, "a track name")
        self.assertEqual(written("a\u3164b", "a track name"), "a\u3164b".encode())

    def test_a_text_name_that_reads_as_rtf_is_refused(self):
        with self.assertRaisesRegex(ValueError, "rtf"):
            plain_text_payload("{\\rtf1 Hidden}")
        self.assertEqual(_text(plain_text_payload("{Intro}")), "{Intro}")

    def test_joined_emoji_and_plain_text_pass(self):
        self.assertEqual(written("👩‍🎤 Lead", "a marker name"), "👩‍🎤 Lead".encode())
        self.assertEqual(written("Verse 2", "a section name"), b"Verse 2")

    def test_the_limit_counts_bytes_and_empty_is_by_permission(self):
        with self.assertRaises(ValueError):
            written("ü" * 4, "a group name", limit=7)
        with self.assertRaises(ValueError):
            written("", "a track name")
        self.assertEqual(written("", "a group name", empty=True), b"")


if __name__ == "__main__":
    unittest.main()
