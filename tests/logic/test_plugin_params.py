"""Parameter tables for Logic's own plug-ins: name -> float index, measured, one JSON per type
in the package data; `decode` reads a float block by name and `encode` patches one."""

import json
import tempfile
import unittest
from pathlib import Path

from _fixtures import chunk
from logicxkit.logic.services.mixer.plugin_params import Table, decode, load_table, load_tables, set_by_name, table_for

TABLE = {"type": 999, "name": "Test Comp", "floats": 6, "opaque": [0],
         "params": [{"index": 1, "name": "Threshold", "unit": "dB", "min": -60, "max": 0, "default": -20},
                    {"index": 2, "name": "Ratio", "unit": ":1", "min": 1, "max": 30, "default": 2},
                    {"index": 3, "name": "Auto Gain", "unit": "", "min": 0, "max": 1, "default": 0,
                     "choices": ["Off", "On"]}],
         "evidence": "a synthetic table"}


class LoadTest(unittest.TestCase):
    def test_a_table_loads_by_type_and_name(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "params-999.json").write_text(json.dumps(TABLE))
            tables = load_tables([Path(td)])
            self.assertEqual(sorted(tables), [999])
            table = tables[999]
            self.assertIsInstance(table, Table)
            self.assertEqual((table.name, table.floats, table.index("Ratio")), ("Test Comp", 6, 2))
            self.assertEqual(load_table(999, [Path(td)]).name, "Test Comp")

    def test_a_name_is_matched_loosely(self):
        table = Table.from_dict(TABLE)
        self.assertEqual(table.index("ratio"), 2)
        self.assertEqual(table.index("auto_gain"), 3)
        with self.assertRaises(KeyError):
            table.index("Attack")


class DecodeTest(unittest.TestCase):
    def test_floats_read_back_by_name(self):
        table = Table.from_dict(TABLE)
        self.assertEqual(decode(table, [0.0, -18.5, 4.0, 1.0, 7.0, 8.0]),
                         {"Threshold": -18.5, "Ratio": 4.0, "Auto Gain": "On"})

    def test_a_short_block_reads_what_it_has(self):
        table = Table.from_dict(TABLE)
        self.assertEqual(decode(table, [0.0, -18.5]), {"Threshold": -18.5})


def _bits(n: int) -> float:
    """The float32 whose bits are the int32 ``n`` — what a float list holds for an integer word."""
    import struct
    return struct.unpack("<f", struct.pack("<i", n))[0]


INTS = {"type": 998, "name": "Test Organ", "floats": 3, "opaque": [0],
        "params": [{"index": 1, "name": "Drawbar", "kind": "int", "default": 8},
                   {"index": 2, "name": "Level", "unit": "dB", "default": 0.0}],
        "evidence": "a synthetic table"}


class IntegerWordTest(unittest.TestCase):
    """Vintage B3 keeps its drawbars as int32 words inside its float block (`instrument-params-vintage-b3-*`):
    a table names such a word's kind, and it reads and writes as the integer, not the denormal float."""

    def test_an_int_word_decodes_to_its_integer(self):
        table = Table.from_dict(INTS)
        self.assertEqual(decode(table, [0.0, _bits(8), -3.0]), {"Drawbar": 8, "Level": -3.0})

    def test_an_int_word_is_written_as_its_bits(self):
        table = Table.from_dict(INTS)
        payload = bytes(60) + chunk(998, [0.0, _bits(8), -3.0])
        out = set_by_name(table, payload, {"Drawbar": 7, "Level": -6})
        import struct
        from logicxkit.logic._binary import FLOAT_OFFSET, find_blocks
        idx, _t, _n = find_blocks(out)[0]
        self.assertEqual(struct.unpack_from("<if", out, idx + FLOAT_OFFSET + 4), (7, -6.0))


PAST = {"type": 216, "name": "Test Organ", "floats": 2, "opaque": [0],
        "params": [{"index": 1, "name": "Drawbar", "kind": "int", "default": 8},
                   {"offset": 32, "name": "Pedal 16'", "default": 8.0},
                   {"offset": 36, "name": "Percussion", "kind": "int", "default": 1}],
        "evidence": "a synthetic table"}


class PastTheBlockTest(unittest.TestCase):
    """Vintage B3 keeps most of its state as plain words after its float block, at fixed payload
    offsets (`instrument-params-vintage-b3-code*`): a table names such a word by ``offset``, and
    the payload decode reads it beside the block's."""

    def _payload(self) -> bytes:
        import struct
        body = chunk(216, [0.0, _bits(8)])                       # the block: 32 bytes from offset 0
        return body + struct.pack("<fi", 8.0, 1) + bytes(8)

    def test_offset_words_read_beside_the_block(self):
        from logicxkit.logic.services.mixer.plugin_params import decode_payload
        table = Table.from_dict(PAST)
        self.assertEqual(decode_payload(table, self._payload()), {"Drawbar": 8, "Pedal 16'": 8.0, "Percussion": 1})
        self.assertEqual(decode(table, [0.0, _bits(8)]), {"Drawbar": 8})   # the float decode: the block alone

    def test_offset_words_are_written_in_place(self):
        import struct
        table = Table.from_dict(PAST)
        out = set_by_name(table, self._payload(), {"Pedal 16'": 5, "Percussion": 0, "Drawbar": 7})
        self.assertEqual(struct.unpack_from("<fi", out, 32), (5.0, 0))
        self.assertEqual(len(out), len(self._payload()))


TEXT = {"type": 313, "name": "Test Alchemy", "floats": 0, "state": "text", "opaque": [],
        "params": [{"key": "alchemypreset[1].F1Cut", "name": "Filter 1 Cutoff", "unit": "%", "scale": 100, "default": 0.13},
                   {"key": "alchemypreset[1].F1On", "name": "Filter 1 On", "choices": ["Off", "On"], "default": 1}],
        "evidence": "a synthetic table"}


class TextStateTest(unittest.TestCase):
    """Alchemy keeps its state as text after the marker `46ia`, one `Key = value…` line each
    (`instrument-params-alchemy-*`): a text table names a key, and the first field, times the
    scale, is the value Logic shows."""

    PAYLOAD = bytes(166) + b"46ia\x00\x00\r\n<alchemypreset>\r\nVersion = 166\r\nF1On = 1\r\nF1Cut = 0.0013 0.0000 6\r\nF1Res = 0.0974\r\n"

    def test_text_keys_read_by_name(self):
        from logicxkit.logic.services.mixer.plugin_params import decode_payload
        table = Table.from_dict(TEXT)
        self.assertEqual(decode_payload(table, self.PAYLOAD), {"Filter 1 Cutoff": 0.13, "Filter 1 On": "On"})

    def test_a_text_table_is_not_written(self):
        table = Table.from_dict(TEXT)
        with self.assertRaises(ValueError) as e:
            set_by_name(table, self.PAYLOAD, {"Filter 1 Cutoff": 50})
        self.assertIn("text", str(e.exception))


class EncodeTest(unittest.TestCase):
    def test_a_value_lands_at_its_index_in_the_chunk(self):
        table = Table.from_dict(TABLE)
        raw = chunk(999, [0.0] * 6)
        out = set_by_name(table, raw, {"ratio": 3.5, "Auto Gain": "On"})
        from logicxkit.logic._binary import find_blocks, read_block_floats
        idx, type_id, n = find_blocks(out)[0]
        self.assertEqual((type_id, read_block_floats(out, idx, n)[1:4]), (999, [0.0, 3.5, 1.0]))

    def test_out_of_range_and_unknown_names_are_refused(self):
        table = Table.from_dict(TABLE)
        raw = chunk(999, [0.0] * 6)
        with self.assertRaises(ValueError):
            set_by_name(table, raw, {"Threshold": 5})
        with self.assertRaises(KeyError):
            set_by_name(table, raw, {"Attack": 5})

    def test_a_choice_by_name_or_number(self):
        table = Table.from_dict(TABLE)
        raw = chunk(999, [0.0] * 6)
        from logicxkit.logic._binary import find_blocks, read_block_floats
        for value in ("On", 1, "1"):
            out = set_by_name(table, raw, {"Auto Gain": value})
            idx, _t, n = find_blocks(out)[0]
            self.assertEqual(read_block_floats(out, idx, n)[3], 1.0)


class VariantTest(unittest.TestCase):
    """One block type, several plug-ins: a table names its variant base and is found by it."""

    def _tables(self, td):
        for stem, type_id, variant, name in (("params-147", 147, 216, "Echo"), ("params-147v200", 147, 200, "Tape Delay"),
                                             ("params-150", 150, None, "SilverVerb")):
            d = {"type": type_id, "name": name, "floats": 4, "params": [{"index": 1, "name": "Dry"}]}
            if variant is not None:
                d["variant"] = variant
            (Path(td) / f"{stem}.json").write_text(json.dumps(d))
        return load_tables([Path(td)])

    def test_keys_by_type_and_by_type_and_variant(self):
        with tempfile.TemporaryDirectory() as td:
            t = self._tables(td)
            self.assertEqual({k: v.name for k, v in t.items()},
                             {147: "Echo", (147, 216): "Echo", (147, 200): "Tape Delay", 150: "SilverVerb"})

    def test_table_for_takes_the_variant_first_then_the_type(self):
        with tempfile.TemporaryDirectory() as td:
            t = self._tables(td)
            self.assertEqual(table_for(t, 147, 200).name, "Tape Delay")
            self.assertEqual(table_for(t, 147, 216).name, "Echo")
            self.assertEqual(table_for(t, 147, None).name, "Echo")        # a record without a variant (v2): the type's
            self.assertIsNone(table_for(t, 147, 999))                      # a member of the family with no table yet
            self.assertEqual(table_for(t, 150, 249).name, "SilverVerb")    # a table naming no variant serves every record
            self.assertIsNone(table_for(t, 151, 1))


class SharpKeysTest(unittest.TestCase):
    """A parameter name keeps its sharp or flat: EVOC 20 TrackOscillator's "Quantize C" and
    "Quantize C♯" are two words, as are Transposer's "C" and "C#"."""

    def test_sharps_and_flats_are_distinct_names(self):
        table = Table.from_dict({"type": 998, "name": "Notes", "floats": 4, "opaque": [0], "evidence": "synthetic",
                                 "params": [{"index": 0, "name": "Quantize C", "default": 0},
                                            {"index": 1, "name": "Quantize C♯", "default": 0},
                                            {"index": 2, "name": "Quantize D♭", "default": 0},
                                            {"index": 3, "name": "C#", "default": 0}]})
        self.assertEqual([table.index("Quantize C"), table.index("Quantize C♯"), table.index("Quantize D♭"), table.index("C#")], [0, 1, 2, 3])
        self.assertEqual(table.index("quantize c sharp"), 1)

    def test_two_parameters_with_one_key_are_refused(self):
        with self.assertRaises(ValueError):
            Table.from_dict({"type": 998, "name": "Dupes", "floats": 2, "opaque": [0], "evidence": "synthetic",
                             "params": [{"index": 0, "name": "Rate", "default": 0}, {"index": 1, "name": "rate", "default": 0}]})

    def test_every_packaged_table_loads_with_distinct_keys_and_indices(self):
        from logicxkit.utils.data import PACKAGED
        for f in sorted((PACKAGED / "logic").glob("params-*.json")):
            with self.subTest(f.name):
                d = json.loads(f.read_text())
                table = Table.from_dict(d)
                words = [(p.index, p.offset) for p in table.params if p.key is None]
                self.assertEqual(len(words), len(set(words)), "two parameters on one word")
                self.assertFalse({p.name for p in table.params} & set(d.get("unmapped", [])), "unmapped and named at once")
                self.assertTrue(all(p.kind in ("float", "int") for p in table.params if p.offset is not None))


class ScaledFloatTest(unittest.TestCase):
    """A float that moves by a multiple of what Logic shows carries ``scale``: the Vintage
    Graphic EQ's bands move 0.2 per 0.1 dB (`instrument-params-vintage-graphic-eq-spots`)."""

    SCALED = {"type": 997, "name": "Scaled", "floats": 3, "opaque": [0], "evidence": "synthetic",
              "params": [{"index": 1, "name": "8.0K", "unit": "dB", "scale": 0.5, "default": 0.0},
                         {"index": 2, "name": "Volume", "unit": "dB", "default": 0.0}]}

    def test_decode_shows_the_word_times_its_scale(self):
        table = Table.from_dict(self.SCALED)
        self.assertEqual(decode(table, [0.0, 0.2, 0.1]), {"8.0K": 0.1, "Volume": 0.1})

    def test_set_writes_the_shown_value_over_its_scale(self):
        from logicxkit.logic.services.mixer.plugin_params import decode_payload
        table = Table.from_dict(self.SCALED)
        out = set_by_name(table, chunk(997, [0.0, 0.0, 0.0]), {"8.0K": -1.5, "Volume": 2.0})
        self.assertEqual(decode_payload(table, out), {"8.0K": -1.5, "Volume": 2.0})
        from logicxkit.logic._binary import find_blocks, read_block_floats
        idx, _t, n = find_blocks(out)[0]
        self.assertEqual(list(read_block_floats(out, idx, n)), [0.0, -3.0, 2.0])


class EveryCopyTest(unittest.TestCase):
    """A save made after a parameter moved carries a second copy of the block (the compare state);
    `set_by_name` writes every same-size copy and the offset words of each, so the file does not
    disagree with itself (`instrument-params-vintage-b3-spots`: the second copy 1660 bytes on)."""

    def _payload(self) -> bytes:
        import struct
        first = chunk(216, [0.0, _bits(8)]) + struct.pack("<fi", 8.0, 1) + bytes(8)
        return first + first                               # the compare copy: block and offset words again

    def test_both_copies_take_the_new_values(self):
        import struct
        from logicxkit.logic._binary import find_blocks, read_block_floats
        table = Table.from_dict(PAST)
        out = set_by_name(table, self._payload(), {"Pedal 16'": 5, "Drawbar": 7})
        copies = find_blocks(out)
        self.assertEqual(len(copies), 2)
        for idx, _t, n in copies:
            self.assertEqual(int_word_of(read_block_floats(out, idx, n)[1]), 7)
        half = len(out) // 2
        self.assertEqual((struct.unpack_from("<f", out, 32)[0], struct.unpack_from("<f", out, half + 32)[0]), (5.0, 5.0))


def int_word_of(value: float) -> int:
    from logicxkit.logic.services.mixer.plugin_params import int_word
    return int_word(value)


if __name__ == "__main__":
    unittest.main()
