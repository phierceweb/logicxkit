"""Insert plugin-slot records into a project's channels.

This is what actually changes a channel's chain. The `.cst` reference is only the label on
Logic's Setting button — Logic renders the embedded slot records, so a channel with no slot
records has an empty Audio FX column no matter what it references.

Slot records are cloned from a donor *inside the same project*, so the record class version
matches exactly (Logic 11.2.2 writes `AuCU` v4; a v5 record from a modern `.cst` would be a
foreign schema). Two things must be rewritten per clone: the owner id (u16 @ +14) and the
per-instance id in the payload — two same-preset slots on different channels differ only
there, so reusing one verbatim would give every channel the same instance.
"""

import struct
import unittest

from logicxkit.logic import insert_slots, project_records

HDR = 36


def rec(tag: bytes, owner: int, key: int, payload: bytes, ver: int = 4) -> bytes:
    h = bytearray(HDR)
    h[0:4] = tag
    struct.pack_into("<H", h, 4, ver)
    struct.pack_into("<H", h, 14, owner)
    struct.pack_into("<H", h, 18, key)
    struct.pack_into("<I", h, 28, len(payload))
    return bytes(h) + payload


def _chan(size: int = 225, fmt: int = 1) -> bytes:
    """A channel payload with a REALISTIC width byte — the guard rejects filler, as it should."""
    p = bytearray(size)
    p[123] = fmt
    return bytes(p)


def proj(*records: bytes) -> bytes:
    body = b"".join(records)
    head = bytearray(24)
    head[0:4] = b"\x23\x47\xc0\xab"
    struct.pack_into("<I", head, 0x10, len(body))
    return bytes(head) + body


class ProjectRecordsTest(unittest.TestCase):
    def test_walks_from_offset_24_and_reaches_eof(self):
        data = proj(rec(b"OCuA", 0, 0xFFFF, _chan(200)), rec(b"UCuA", 0, 10, b"R" * 8))
        got = project_records(data)
        self.assertEqual([(r.owner, r.key) for r in got], [(0, 0xFFFF), (0, 10)])

    def test_tag_bytes_are_the_raw_on_disk_form(self):
        """Logic's tags read reversed: the channel record's bytes are OCuA, not AuCO. Matching
        the display form silently finds nothing in a real project."""
        from logicxkit.logic.services.insert import CHANNEL_TAG
        self.assertEqual(CHANNEL_TAG, b"OCuA")

    def test_accepts_the_many_tag_types_a_project_uses(self):
        data = proj(rec(b"gRuA", 0, 0xFFFF, b"x" * 8), rec(b"Snog", 0, 0xFFFF, b"y" * 8),
                    rec(b"OCuA", 1, 0xFFFF, b"z" * 8))
        self.assertEqual(len(project_records(data)), 3)


class InsertSlotsTest(unittest.TestCase):
    def setUp(self):
        self.donor = rec(b"UCuA", 67, 4, b"E" * 100 + b"IDIDIDID")  # tail carries the instance id
        self.data = proj(
            rec(b"OCuA", 0, 0xFFFF, _chan(200)), rec(b"UCuA", 0, 10, b"REF"),
            rec(b"OCuA", 1, 0xFFFF, _chan(200)), rec(b"UCuA", 1, 10, b"REF"),
        )

    def test_inserts_after_the_channel_record(self):
        out = insert_slots(self.data, {0: [(self.donor, 4, None, 0)]})
        keys = [(r.owner, r.key) for r in project_records(out)]
        self.assertEqual(keys, [(0, 0xFFFF), (0, 4), (0, 10), (1, 0xFFFF), (1, 10)])

    def test_clone_takes_the_target_owner(self):
        out = insert_slots(self.data, {1: [(self.donor, 4, None, 0)]})
        added = [r for r in project_records(out) if r.key == 4]
        self.assertEqual([r.owner for r in added], [1])

    def test_header_total_is_updated(self):
        out = insert_slots(self.data, {0: [(self.donor, 4, None, 0)]})
        self.assertEqual(struct.unpack_from("<I", out, 0x10)[0], len(out) - 24)

    def test_length_grows_by_exactly_the_added_records(self):
        out = insert_slots(self.data, {0: [(self.donor, 4, None, 0)]})
        self.assertEqual(len(out) - len(self.data), len(self.donor))

    def test_clones_differ_only_where_verified_id_offsets_say_so(self):
        """With measured offsets each clone gets its own id; without them the payload is
        copied verbatim, because writing at guessed positions destroys real data."""
        with_ids = insert_slots(self.data, {0: [(self.donor, 4, None, 0, None, (104, 105))],
                                            1: [(self.donor, 4, None, 0, None, (104, 105))]})
        bodies = [r.raw[HDR:] for r in project_records(with_ids) if r.key == 4]
        self.assertEqual(len(bodies), 2)
        self.assertNotEqual(bodies[0], bodies[1])
        self.assertEqual([i for i in range(len(bodies[0])) if bodies[0][i] != bodies[1][i]],
                         [104, 105], "only the given offsets may change")

        without = insert_slots(self.data, {0: [(self.donor, 4, None, 0)],
                                           1: [(self.donor, 4, None, 0)]})
        plain = [r.raw[HDR:] for r in project_records(without) if r.key == 4]
        self.assertEqual(plain[0], plain[1])

    def test_unknown_owner_raises(self):
        with self.assertRaises(ValueError):
            insert_slots(self.data, {99: [(self.donor, 4, None, 0)]})

    def test_existing_slots_are_replaced_not_duplicated(self):
        data = proj(rec(b"OCuA", 0, 0xFFFF, _chan(200)), rec(b"UCuA", 0, 4, b"OLD"),
                    rec(b"UCuA", 0, 10, b"REF"))
        out = insert_slots(data, {0: [(self.donor, 4, None, 0)]})
        self.assertNotIn(b"OLD", out)
        self.assertEqual([(r.owner, r.key) for r in project_records(out)],
                         [(0, 0xFFFF), (0, 4), (0, 10)])


class StubChannelRecordTest(unittest.TestCase):
    """A channel can be preceded by a 14-byte OCuA stub (owner 0 in one legacy song has one).
    Inserting after the FIRST matching OCuA attaches the slots to the stub, so the real
    channel shows no chain — Audio 1 came out empty while every other channel worked."""

    def setUp(self):
        self.donor = rec(b"UCuA", 67, 4, b"E" * 100 + b"IDIDIDID")
        self.data = proj(
            rec(b"OCuA", 0, 0xFFFF, b"\x00" * 14),   # stub
            rec(b"OCuA", 0, 0xFFFF, _chan(225)),     # the real channel record
            rec(b"UCuA", 0, 10, b"REF"),
        )

    def test_slots_attach_to_the_real_channel_not_the_stub(self):
        out = insert_slots(self.data, {0: [(self.donor, 4, None, 0)]})
        sizes = [(r.tag, r.key, len(r.raw) - 36) for r in project_records(out)]
        self.assertEqual(sizes, [(b"OCuA", 0xFFFF, 14), (b"OCuA", 0xFFFF, 225),
                                 (b"UCuA", 4, 108), (b"UCuA", 10, 3)])

    def test_channel_with_no_satellites_still_gets_slots(self):
        data = proj(rec(b"OCuA", 3, 0xFFFF, _chan(225)))
        out = insert_slots(data, {3: [(self.donor, 4, None, 0)]})
        self.assertEqual([(r.tag, r.key) for r in project_records(out)],
                         [(b"OCuA", 0xFFFF), (b"UCuA", 4)])


class SlotLabelTest(unittest.TestCase):
    """An inserted slot inherits the donor's preset label, so a kick channel would read
    'Brighten Overheads'. The label is a null-padded field, so it can be rewritten in place."""

    def _slot(self, label: str) -> bytes:
        payload = b"\x00" * 14 + label.encode() + b"\x00" * (62 - len(label)) + b"TAIL" * 4
        return rec(b"UCuA", 67, 4, payload)

    def test_relabels_without_changing_length(self):
        from logicxkit.logic import relabel_slot
        src = self._slot("Brighten Overheads.pst")
        out = relabel_slot(src, "Trk - Kick In")
        self.assertEqual(len(out), len(src))
        self.assertIn(b"Trk - Kick In.pst", out)
        self.assertNotIn(b"Brighten", out)

    def test_leaves_a_record_with_no_label_untouched(self):
        from logicxkit.logic import relabel_slot
        src = rec(b"UCuA", 67, 4, b"\x00" * 40)
        self.assertEqual(relabel_slot(src, "Anything"), src)

    def test_rejects_a_label_too_long_for_the_field(self):
        from logicxkit.logic import relabel_slot
        with self.assertRaises(ValueError):
            relabel_slot(self._slot("Short.pst"), "x" * 200)


class ChannelFormatTest(unittest.TestCase):
    """A plugin instance carries its channel count, and it must match the channel it sits on.

    Verified across 50 native instances in 6 projects: the channel record holds 1 (mono) or
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


class VerifiedInstanceIdTest(unittest.TestCase):
    """Per-instance id bytes sit in the trailer at PLUGIN-SPECIFIC positions — Channel EQ uses
    payload-18,-17,-12..-5 while Enveloper uses -20..-17,-12..-5. Assuming one layout for all
    plugins overwrites real data (it corrupted 5 bytes of every Enveloper and broke the file).
    Offsets are therefore derived from real instances, and when they cannot be derived nothing
    is written."""

    def test_derives_offsets_from_two_instances(self):
        from logicxkit.logic import instance_offsets
        a = bytearray(100)
        b = bytearray(100)
        b[90] = 7
        b[95] = 9
        self.assertEqual(instance_offsets([bytes(a), bytes(b)], chunk_end=80), [90, 95])

    def test_ignores_differences_inside_the_parameter_chunk(self):
        from logicxkit.logic import instance_offsets
        a = bytearray(100)
        b = bytearray(100)
        b[50] = 3          # a parameter value, not an instance id
        b[95] = 9
        self.assertEqual(instance_offsets([bytes(a), bytes(b)], chunk_end=80), [95])

    def test_single_instance_yields_nothing(self):
        from logicxkit.logic import instance_offsets
        self.assertEqual(instance_offsets([bytes(100)], chunk_end=80), [])

    def test_stamp_without_offsets_touches_only_the_slot_index(self):
        """The slot index is structural and always written; the per-instance id is not."""
        from logicxkit.logic.services.insert import SLOT_INDEX_AT, _stamp
        donor = rec(b"UCuA", 9, 4, bytes(range(60)))
        out = _stamp(donor, owner=1, key=4, floats=None, limit=0, seed="x",
                     label=None, fmt=None, id_offsets=())
        changed = {i for i in range(60) if out[36 + i] != donor[36 + i]}
        self.assertEqual(changed, {SLOT_INDEX_AT})

    def test_stamp_writes_only_the_given_offsets(self):
        from logicxkit.logic.services.insert import SLOT_INDEX_AT, _stamp
        donor = rec(b"UCuA", 9, 4, bytes(60))
        out = _stamp(donor, owner=1, key=4, floats=None, limit=0, seed="x",
                     label=None, fmt=None, id_offsets=(50, 51))
        changed = {i for i in range(60) if out[36 + i] != donor[36 + i]}
        self.assertTrue(changed <= {50, 51, SLOT_INDEX_AT})


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


class SlotBypassTest(unittest.TestCase):
    """Payload +112 is a 0/1 flag that Logic itself writes both ways, and it is the only
    unexplained varying byte in a slot record. Every one of the 27 active slots on hand reads 0,
    while a live template mixes 13 ones and 16 zeros — consistent with 0 = on, 1 = bypassed.

    Confirmed in Logic: a build written with 1 on nine Enveloper slots opened with them
    bypassed; after they were enabled by hand the flag read 0 on exactly those channels, while
    the untouched ones still read 1.
    """

    def _slot(self) -> bytes:
        payload = bytearray(200)
        payload[112] = 0
        return rec(b"UCuA", 5, 4, bytes(payload))

    def test_sets_and_clears(self):
        from logicxkit.logic import set_slot_bypass, slot_bypassed
        on = set_slot_bypass(self._slot(), True)
        self.assertTrue(slot_bypassed(on))
        self.assertFalse(slot_bypassed(set_slot_bypass(on, False)))

    def test_changes_exactly_one_byte(self):
        from logicxkit.logic import set_slot_bypass
        src = self._slot()
        out = set_slot_bypass(src, True)
        self.assertEqual([i for i in range(len(src)) if src[i] != out[i]], [36 + 112])

    def test_length_preserved(self):
        from logicxkit.logic import set_slot_bypass
        self.assertEqual(len(set_slot_bypass(self._slot(), True)), len(self._slot()))


class SlotIndexTest(unittest.TestCase):
    """Payload +6 is the slot's index within its channel, and Logic writes it as key - 3
    (verified in Logic-written files: keys 4,5,6 -> 1,2,3; keys 3,4 -> 0,1).

    A clone inherits the donor's value, so two slots end up claiming the same index and Logic
    renders only one of them — the snare-bottom EQ vanished behind the Gain this way, and the
    compressor was hidden behind the Enveloper on every three-slot channel.
    """

    def _slot(self, donor_index: int) -> bytes:
        payload = bytearray(200)
        payload[6] = donor_index
        return rec(b"UCuA", 9, 4, bytes(payload))

    def test_index_follows_the_key(self):
        """Default base 4 (Logic 11.2/12): key 4 is index 0."""
        from logicxkit.logic.services.insert import _stamp
        for key, want in ((4, 0), (5, 1), (6, 2), (7, 3)):
            out = _stamp(self._slot(9), owner=1, key=key, floats=None, limit=0, seed="s")
            self.assertEqual(out[36 + 6], want, f"key {key} must write index {want}")

    def test_four_slots_get_four_distinct_indices(self):
        from logicxkit.logic import insert_slots, project_records
        chan = bytearray(225)
        chan[123] = 1
        data = proj(rec(b"OCuA", 0, 0xFFFF, bytes(chan)))
        donor = self._slot(0)
        out = insert_slots(data, {0: [(donor, k, None, 0) for k in (4, 5, 6, 7)]})
        idx = [r.raw[36 + 6] for r in project_records(out) if r.key in (4, 5, 6, 7)]
        self.assertEqual(idx, [0, 1, 2, 3])
        self.assertEqual(len(set(idx)), 4, "indices must be unique or Logic hides a slot")


class SlotIndexBaseTest(unittest.TestCase):
    """The slot index is the 0-based position among insert slots, but the KEY those slots start
    at moves with the schema — Logic 11.0 writes slots from key 3 (index = key-3) while 11.2/12
    writes them from key 4 (index = key-4). The base is therefore derived from the project's own
    Logic-written slots rather than hardcoded."""

    def _slot(self, key: int, index: int) -> bytes:
        payload = bytearray(200)
        payload[6] = index
        payload[184:184 + 8] = b"GAMETSPP"
        struct.pack_into("<III", payload, 172, 24 + 16, 1, 4)
        struct.pack_into("<I", payload, 192, 236)
        return rec(b"UCuA", 0, key, bytes(payload))

    def test_derives_base_from_existing_slots(self):
        from logicxkit.logic import slot_index_base
        data = proj(rec(b"OCuA", 0, 0xFFFF, _chan(225)), self._slot(4, 0))
        self.assertEqual(slot_index_base(data), 4)
        older = proj(rec(b"OCuA", 0, 0xFFFF, _chan(225)), self._slot(3, 0))
        self.assertEqual(slot_index_base(older), 3)

    def test_defaults_when_the_project_has_no_slots(self):
        from logicxkit.logic import slot_index_base
        self.assertEqual(slot_index_base(proj(rec(b"OCuA", 0, 0xFFFF, _chan(225)))), 4)

    def test_inserted_slots_continue_the_projects_own_numbering(self):
        from logicxkit.logic import insert_slots, project_records
        chan = bytearray(225)
        chan[123] = 1
        data = proj(rec(b"OCuA", 0, 0xFFFF, bytes(chan)),
                    rec(b"OCuA", 1, 0xFFFF, bytes(chan)), self._slot(4, 0))
        donor = self._slot(4, 0)
        out = insert_slots(data, {1: [(donor, k, None, 0) for k in (4, 5, 6)]})
        got = [r.raw[36 + 6] for r in project_records(out)
               if r.owner == 1 and r.tag == b"UCuA"]
        self.assertEqual(got, [0, 1, 2], "must match how Logic numbers this project")


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

    def test_real_conversion_of_an_unmapped_plugin_still_raises(self):
        from logicxkit.logic import set_slot_format
        with self.assertRaises(ValueError):
            set_slot_format(self._slot(1, 166), 2)

    def test_stereo_donor_onto_stereo_channel_survives_insert(self):
        from logicxkit.logic import insert_slots, project_records, slot_format
        chan = bytearray(225)
        chan[123] = 2
        data = proj(rec(b"OCuA", 0, 0xFFFF, bytes(chan)))
        out = insert_slots(data, {0: [(self._slot(2, 166), 4, None, 0)]})
        got = [r for r in project_records(out) if r.key == 4][0]
        self.assertEqual(slot_format(got.raw), 2)

