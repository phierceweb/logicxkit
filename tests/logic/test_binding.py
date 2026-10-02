"""Which Environment object a mixer channel is bound to, and where it routes.

Both sit at the END of the `OCuA` payload because its length varies per session (257, 265,
269 bytes at one class version): `[len-48:len-32]` is the bound object's UUID, `[len-32:len-16]`
the destination channel's own UUID. `+110` is the Sub number of the channel's stack.
Holds on every in-use channel of the sessions measured and the Recording template,
2026-09-01."""

import struct
import unittest
from _records import chan, count_record, env_obj, proj, uuid
from logicxkit.logic.services.binding import (
    bound_channels,
    bound_objects,
    channels,
    input_labels,
    input_routing,
    output_labels,
    output_routing,
    set_stack_index,
    stack_channels,
)


def _session():
    return proj(
        env_obj(192, "Drums", grouping=True, uuid=uuid(192)),
        env_obj(88, "Kick In", uuid=uuid(88)),
        env_obj(80, "Master", grouping=True, uuid=uuid(80)),
        chan(378, "Sub 1", uuid=uuid(192)),
        chan(0, "Audio 1", uuid=uuid(88), dest=uuid(1001), stack_index=1),
        chan(121, "Bus 1", uuid=uuid(1001), dest=uuid(80), size=201),
        chan(401, "Output 1-2", uuid=uuid(80), size=201),
        chan(26, "Audio 27", in_use=False),
    )


class ChannelsTest(unittest.TestCase):
    def test_label_in_use_and_stack_index(self):
        c = channels(_session())
        self.assertEqual(c[0].label, "Audio 1")
        self.assertTrue(c[0].in_use)
        self.assertEqual(c[0].stack_index, 1)
        self.assertFalse(c[26].in_use)

    def test_tail_fields_are_length_relative(self):
        c = channels(_session())
        self.assertEqual(c[121].uuid, uuid(1001))       # a 201-byte record
        self.assertEqual(c[0].uuid, uuid(88))            # a 257-byte record


class LinkTest(unittest.TestCase):
    def test_owner_to_object_and_back(self):
        self.assertEqual(bound_objects(_session())[0], 88)
        self.assertEqual(bound_channels(_session())[192], 378)

    def test_unbound_stub_is_absent(self):
        self.assertNotIn(26, bound_objects(_session()))


class RoutingTest(unittest.TestCase):
    def test_destination_resolves_to_the_bus_owner(self):
        self.assertEqual(output_routing(_session())[0], 121)

    def test_a_zero_destination_is_none(self):
        self.assertIsNone(output_routing(_session())[401])


class StackChannelTest(unittest.TestCase):
    def test_sub_number_maps_to_owner(self):
        self.assertEqual(stack_channels(_session()), {1: 378})

    def test_set_stack_index_touches_one_byte(self):
        raw = chan(0, "Audio 1")
        out = set_stack_index(raw, 3)
        diffs = [i for i, (a, b) in enumerate(zip(raw, out, strict=True)) if a != b]
        self.assertEqual(diffs, [36 + 110])
        self.assertEqual(out[36 + 110], 3)


class NamelessObjectTest(unittest.TestCase):
    def test_a_channel_bound_to_an_object_whose_name_does_not_decode_is_bound(self):
        data = proj(env_obj(500, b"Gitarre \xfc"), chan(272, "Audio 1", uuid=uuid(500)))
        self.assertEqual(bound_channels(data), {500: 272})


def _logic_11_2():
    """Objects typed 1760 over class-6 channel records: the uuid is the last 16 bytes."""
    return proj(
        env_obj(192, "Drums", grouping=True, type_value=1760),
        env_obj(88, "Piano", type_value=1760),
        chan(378, "Sub 1", uuid=uuid(192), size=233, ver=6),
        chan(5, "Inst 1", uuid=uuid(88), size=225, ver=6),
        chan(26, "Audio 27", in_use=False, size=233, ver=6),
    )


class Class6Test(unittest.TestCase):
    def test_the_own_uuid_is_the_last_16_bytes(self):
        c = channels(_logic_11_2())[5]
        self.assertEqual((c.uuid, c.ver), (uuid(88), 6))

    def test_a_channel_binds_whatever_its_size(self):
        self.assertEqual(bound_objects(_logic_11_2()), {378: 192, 5: 88})

    def test_it_carries_no_routing_uuid(self):
        data = _logic_11_2()
        self.assertEqual((output_routing(data), input_routing(data)), ({}, {}))
        self.assertEqual(channels(data)[5].dest_uuid, bytes(16))

    def test_class_7_is_read_as_before(self):
        c = channels(_session())[0]
        self.assertEqual((c.uuid, c.dest_uuid, c.ver), (uuid(88), uuid(1001), 7))


class WhatDoesNotBindTest(unittest.TestCase):
    def test_a_free_stub_that_names_its_input_stays_unbound(self):
        data = proj(env_obj(500, "Input 1"), chan(256, "Input 1", uuid=uuid(500), size=201),
                    chan(9, "Audio 10", source=uuid(500), in_use=False, size=265))
        self.assertEqual(bound_objects(data), {256: 500})
        self.assertEqual(bound_channels(data), {500: 256})

    def test_a_zero_uuid_names_nothing(self):
        data = proj(env_obj(300, "FX 03", uuid=bytes(16)), chan(9, "Bus 1", in_use=False, size=201))
        self.assertEqual(bound_objects(data), {})

    def test_a_class_no_file_here_has_reads_with_no_uuids(self):
        raw = bytearray(chan(5, "Inst 1", uuid=uuid(88), dest=uuid(9), source=uuid(7)))
        struct.pack_into("<H", raw, 4, 8)
        data = proj(env_obj(88, "Piano"), bytes(raw))
        c = channels(data)[5]
        self.assertEqual((c.uuid, c.dest_uuid, c.input_uuid), (bytes(16),) * 3)
        self.assertEqual(bound_objects(data), {})


def _indexed(fmt: int = 2511, inputs: int | None = 32) -> bytes:
    """A Logic 11.2 mixer on a 32-input device: class-6 records, routed by their index words."""
    count = [count_record(1, [0, 0, 0, 0, inputs], 1)] if inputs else []
    data = bytearray(proj(
        *count,
        chan(0, "Audio 1", size=233, ver=6, words=(22, 24)),
        chan(1, "Audio 2", size=233, ver=6, words=(0, 0), stereo_input=True),
        chan(288, "Aux 1", size=233, ver=6, words=(0, 16), stereo_input=True),
        chan(291, "Aux 4", size=233, ver=6, words=(28, 41)),
        chan(300, "Aux 13", size=233, ver=6, words=(0, 16 + 258), stereo_input=True),
        chan(303, "Inst 1", size=233, ver=6, words=(18, 0xFFFF)),
        chan(848, "Sub 1", size=233, ver=6, words=(0, 0))))
    struct.pack_into("<H", data, 4, fmt)
    return bytes(data)


class IndexWordRoutingTest(unittest.TestCase):
    """A class-6 record carries no routing uuid: Logic 11.2 routes by the index words at +92 and
    +94, counted over the device's inputs."""

    def test_an_output_is_an_output_pair_or_a_bus(self):
        self.assertEqual(output_labels(_indexed()),
                         {0: "Bus 7", 1: "Output 1-2", 288: "Output 1-2", 291: "Bus 13",
                          300: "Output 1-2", 303: "Bus 3", 848: None})

    def test_an_audio_input_is_one_input_or_a_pair_by_its_input_format(self):
        found = input_labels(_indexed())
        self.assertEqual((found[0], found[1]), ("Input 25", "Input 1-2"))

    def test_an_aux_counts_its_buses_after_the_inputs_of_its_format(self):
        found = input_labels(_indexed())
        self.assertEqual((found[288], found[291]), ("Bus 1", "Bus 10"))

    def test_an_instrument_and_a_sub_have_no_input(self):
        found = input_labels(_indexed())
        self.assertEqual((found[303], found[848]), (None, None))

    def test_a_source_past_the_buses_is_left_out_not_called_no_input(self):
        self.assertNotIn(300, input_labels(_indexed()))

    def test_without_the_device_count_or_on_an_unmeasured_format_nothing_is_read(self):
        for data in (_indexed(inputs=None), _indexed(fmt=2510)):
            self.assertEqual((output_labels(data), input_labels(data)), ({}, {}))


class UuidRoutingLabelsTest(unittest.TestCase):
    def test_class_7_reads_its_uuids_whatever_the_words_say(self):
        data = proj(chan(0, "Audio 1", uuid=uuid(88), dest=uuid(1001), source=uuid(500),
                         words=(0, 3)),
                    chan(121, "Bus 1", uuid=uuid(1001), size=201),
                    chan(256, "Input 1", uuid=uuid(500), size=201))
        self.assertEqual(output_labels(data), {0: "Bus 1", 121: None, 256: None})
        self.assertEqual(input_labels(data), {0: "Input 1", 121: None, 256: None})

    def test_the_owner_readers_leave_out_a_class_without_routing_uuids(self):
        self.assertEqual((output_routing(_indexed()), input_routing(_indexed())), ({}, {}))
