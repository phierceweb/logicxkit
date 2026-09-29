"""A slot's width: the channel count a plug-in instance carries in seven fields, the variant id
that picks its mono or stereo build, and a width change that is already there being a no-op
(`services/slot_width`)."""

import struct
import unittest

from test_insert import proj, rec


class ChannelFormatTest(unittest.TestCase):
    """A plugin instance carries its channel count, and it must match the channel it sits on.

    Verified across the native instances on hand: the channel record holds 1 (mono) or
    2 (stereo) at payload+123, and the slot record repeats that value at payload offsets
    81, 84, 118, 119, 156, 157. Cloning a mono donor onto a stereo bus therefore yields a
    MONO plugin on a stereo path — which is what was heard on the bus EQs.

    Channel EQ always holds 0 at +157 regardless of format, so only bytes already holding a
    1 or a 2 are rewritten.
    """

    def _slot(self, fmt: int, eq_quirk: bool = False) -> bytes:
        """A Channel-EQ-shaped slot: counts, config index, variant id and bus bytes."""
        payload = bytearray(260)
        for off in (81, 84, 118, 119, 156, 157):
            payload[off] = fmt
        struct.pack_into("<H", payload, 116, 0x04A5 + fmt)   # Channel EQ variant id
        if eq_quirk:
            payload[157] = 0
        payload[184:184 + 8] = b"GAMETSPP"
        struct.pack_into("<III", payload, 172, 24 + 4 * 4, 1, 4)
        struct.pack_into("<I", payload, 192, 236)
        return rec(b"UCuA", 5, 4, bytes(payload))

    def test_reads_format_from_a_slot(self):
        from logicxkit.logic import slot_format
        self.assertEqual(slot_format(self._slot(1)), 1)
        self.assertEqual(slot_format(self._slot(2)), 2)

    def test_converts_mono_donor_to_stereo(self):
        from logicxkit.logic import set_slot_format, slot_format
        out = set_slot_format(self._slot(1), 2)  # type id read from the record
        self.assertEqual(slot_format(out), 2)
        self.assertEqual(len(out), len(self._slot(1)))

    def test_leaves_the_channel_eq_zero_field_alone(self):
        """+157 is 0 on every Channel EQ ever written; writing 2 there would invent a side chain."""
        from logicxkit.logic import set_slot_format
        out = set_slot_format(self._slot(1, eq_quirk=True), 2)
        self.assertEqual(out[36 + 157], 0)
        self.assertEqual(out[36 + 156], 2)

    def test_variant_id_follows_the_width(self):
        from logicxkit.logic import set_slot_format
        out = set_slot_format(self._slot(1), 2)
        self.assertEqual(struct.unpack_from("<H", out, 36 + 116)[0], 0x04A7)

    def test_channel_formats_reads_the_channel_record(self):
        from logicxkit.logic import channel_formats
        chan = bytearray(225)
        chan[123] = 2
        data = proj(rec(b"OCuA", 7, 0xFFFF, bytes(chan)))
        self.assertEqual(channel_formats(data), {7: 2})

    def test_insert_matches_the_slot_to_its_channel(self):
        from logicxkit.logic import insert_slots, project_records, slot_format
        chan_mono = bytearray(225)
        chan_mono[123] = 1
        chan_stereo = bytearray(225)
        chan_stereo[123] = 2
        data = proj(rec(b"OCuA", 0, 0xFFFF, bytes(chan_mono)),
                    rec(b"OCuA", 1, 0xFFFF, bytes(chan_stereo)))
        donor = self._slot(1)  # a MONO donor
        out = insert_slots(data, {0: [(donor, 4, None, 0)], 1: [(donor, 4, None, 0)]})
        by_owner = {r.owner: r.raw for r in project_records(out) if r.key == 4}
        self.assertEqual(slot_format(by_owner[0]), 1)
        self.assertEqual(slot_format(by_owner[1]), 2, "stereo channel must get a stereo instance")


class PluginVariantIdTest(unittest.TestCase):
    """Width is 7 fields, not 6: a plugin-variant id at payload+116..117 selects the mono or
    stereo BUILD of the plugin. Setting channel counts without it leaves Logic pointed at the
    mono build while told to expect stereo."""

    def _slot(self, tid: int, cfg: int, variant: int) -> bytes:
        payload = bytearray(200)
        payload[81] = cfg
        for off in (84, 118, 119, 156):
            payload[off] = cfg
        struct.pack_into("<H", payload, 116, variant)
        return rec(b"UCuA", 5, 4, bytes(payload))

    def test_widening_channel_eq_updates_the_variant_id(self):
        from logicxkit.logic import set_slot_format
        out = set_slot_format(self._slot(236, 1, 0x04A6), 2, type_id=236)
        self.assertEqual(struct.unpack_from("<H", out, 36 + 116)[0], 0x04A7)
        self.assertEqual(out[36 + 118], 2)

    def test_gain_uses_config_index_three_for_stereo(self):
        """A blanket 2 is wrong: Gain's stereo config index is 3, so its variant id shifts by 2."""
        from logicxkit.logic import set_slot_format
        out = set_slot_format(self._slot(183, 1, 0x0330), 2, type_id=183)
        self.assertEqual(out[36 + 81], 3)
        self.assertEqual(struct.unpack_from("<H", out, 36 + 116)[0], 0x0332)

    def test_echo_widens_with_config_index_two(self):
        """Observed at both widths in Logic-written files: mono cfg 1, stereo cfg 2."""
        from logicxkit.logic import set_slot_format
        out = set_slot_format(self._slot(147, 1, 0x00D9), 2, type_id=147)
        self.assertEqual(out[36 + 81], 2)
        self.assertEqual(struct.unpack_from("<H", out, 36 + 116)[0], 0x00DA)
        self.assertEqual(out[36 + 118], 2)

    def test_unknown_plugin_raises_rather_than_guessing(self):
        from logicxkit.logic import set_slot_format
        with self.assertRaises(ValueError):
            set_slot_format(self._slot(9999, 1, 0x0100), 2, type_id=9999)

    def test_mono_side_chain_is_preserved_when_widening(self):
        """A stereo compressor legitimately keeps a MONO side chain; +157 only follows +156
        when the two already agree."""
        from logicxkit.logic import set_slot_format
        s = bytearray(self._slot(154, 1, 0x0186))
        s[36 + 157] = 1
        s[36 + 156] = 1
        out = set_slot_format(bytes(s), 2, type_id=154)
        self.assertEqual(out[36 + 156], 2)
        self.assertEqual(out[36 + 157], 2)
        s2 = bytearray(self._slot(154, 2, 0x0187))
        s2[36 + 156] = 2
        s2[36 + 157] = 1          # mono side chain on a stereo instance
        out2 = set_slot_format(bytes(s2), 2, type_id=154)
        self.assertEqual(out2[36 + 157], 1, "a mono side chain must survive")


class WidthNoOpTest(unittest.TestCase):
    """Converting width needs a per-plugin config index, known only for mapped plugins. But when
    the donor's width ALREADY matches the target there is nothing to convert — demanding a
    mapping there would block plugins needlessly (it blocked the reverbs)."""

    def _slot(self, fmt: int, type_id: int) -> bytes:
        p = bytearray(220)
        p[81] = fmt
        for off in (84, 118, 119, 156):
            p[off] = fmt
        struct.pack_into("<H", p, 116, 0x0500 + fmt)
        p[184:192] = b"GAMETSPP"
        struct.pack_into("<III", p, 172, 24 + 16, 1, 4)
        struct.pack_into("<I", p, 192, type_id)
        return rec(b"UCuA", 0, 4, bytes(p))

    def test_matching_width_is_a_no_op_even_for_an_unmapped_plugin(self):
        from logicxkit.logic import set_slot_format
        src = self._slot(2, 166)
        self.assertEqual(set_slot_format(src, 2), src)

    def test_a_one_build_plugin_is_left_as_it_is(self):
        """Fuzz-Wah, Spectral Gate and Rotor Cabinet go onto a mono channel as Mono -> Stereo:
        Logic writes the stereo record there too, so nothing is re-stamped."""
        from logicxkit.logic import set_slot_format
        raw = self._slot(2, 155)
        self.assertEqual(set_slot_format(raw, 1), raw)

        from logicxkit.logic import set_slot_format
        with self.assertRaises(ValueError):
            set_slot_format(self._slot(1, 9999), 2)      # no plug-in has this type, so no config is known

    def test_stereo_donor_onto_stereo_channel_survives_insert(self):
        from logicxkit.logic import insert_slots, project_records, slot_format
        chan = bytearray(225)
        chan[123] = 2
        data = proj(rec(b"OCuA", 0, 0xFFFF, bytes(chan)))
        out = insert_slots(data, {0: [(self._slot(2, 166), 4, None, 0)]})
        got = [r for r in project_records(out) if r.key == 4][0]
        self.assertEqual(slot_format(got.raw), 2)


if __name__ == "__main__":
    unittest.main()
