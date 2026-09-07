"""Logic groups: the group triple, the member events, the object's group number and the
registry pair. Synthetic projects prove the structure; the goldens hold the writers to
Logic's own single-change saves when those are on hand."""

import struct
import unittest
import _paths  # noqa: F401
from _records import chan, env_obj, gnos, group_triple, marker, proj, rec, track, uuid
from logicxkit.logic.services.groups import (
    DEFAULT_FLAGS,
    FLAGS,
    assign,
    create_group,
    flags_for,
    group_errors,
    group_of,
    member_events,
    read_groups,
    set_group,
    settings_of,
)
from logicxkit.logic.services.insert import HEADER, project_records
from logicxkit.logic.services.registry import group_entries, register_group
from _data import needs

KICK, SNARE, OH_L, OH_R = 88, 92, 96, 100

IDS = (KICK, SNARE, OH_L, OH_R)


def session(*groups: bytes, numbers: dict[int, int] | None = None, registry: tuple[int, ...] = ()) -> bytes:
    numbers = numbers or {}
    return proj(
        gnos(*IDS, groups=registry),
        rec(b"rpyH", 0xFFFF, 0xFFFF, bytes(40)),
        *groups,
        *(env_obj(oid, name, group=numbers.get(oid, 0))
          for oid, name in zip(IDS, ("Kick In", "Snare Up", "OH L", "OH R"), strict=True)),
        *(chan(k, f"Audio {k + 1}", uuid=uuid(oid)) for k, oid in enumerate(IDS)),
        *(track(k, oid) for k, oid in enumerate(IDS)), marker())


def tags(data: bytes) -> list[bytes]:
    return [r.tag for r in project_records(data)]


def events_of(data: bytes, number: int) -> list[tuple[int, int]]:
    """``(object id, fader)`` per event of group ``number``."""
    g = read_groups(data)[number - 1]
    ev = project_records(data)[g.start + 2].raw[HEADER:]
    return [(struct.unpack_from("<I", ev, k + 4)[0] // 2, ev[k + 12]) for k in range(0, len(ev) - 16, 32)]

class FlagsTest(unittest.TestCase):
    def test_the_fresh_defaults_are_volume_mute_and_automation_mode(self):
        self.assertEqual(settings_of(DEFAULT_FLAGS), ["Volume", "Mute", "Automation Mode"])

    def test_every_box_round_trips_and_the_unknown_bits_survive(self):
        for name in FLAGS:
            flags = flags_for([name], base=DEFAULT_FLAGS)
            self.assertEqual(settings_of(flags), [name], name)
            self.assertEqual(flags >> 31, 1, name)                # bit 31 is not a box

    def test_quantize_locked_is_stored_inverted(self):
        self.assertEqual(flags_for([]) >> 22 & 1, 1)
        self.assertEqual(flags_for(["Quantize-Locked (Audio)"]) >> 22 & 1, 0)

    def test_an_unknown_box_is_refused(self):
        with self.assertRaises(ValueError):
            flags_for(["Loudness"])

    @needs("logic", "group-12.3.1.json")
    def test_member_events_follow_the_faders_only(self):
        self.assertEqual([e[12] for e in _split(member_events(DEFAULT_FLAGS, KICK))], [9, 7])
        self.assertEqual([e[12] for e in _split(member_events(flags_for(["Solo", "Pan"]), KICK))], [3, 10])
        self.assertEqual(member_events(flags_for(["Send 1", "Color"]), KICK), b"")
        self.assertEqual(struct.unpack_from("<I", member_events(DEFAULT_FLAGS, KICK), 4)[0], KICK * 2)

    @needs("logic", "group-12.3.1.json")
    def test_the_event_carries_the_members_value_in_three_places(self):
        volume = _split(member_events(flags_for(["Volume", "Pan"]), KICK, fader=0x5E3DD780, pan=100 << 24))
        self.assertEqual(struct.unpack_from("<I", volume[0], 8)[0], 0x5E3DD780)
        self.assertEqual(struct.unpack_from("<H", volume[0], 20)[0], 0x5E3D)
        self.assertEqual(struct.unpack_from("<H", volume[0], 30)[0], 0xD780)
        self.assertEqual((volume[1][12], volume[1][11]), (10, 100))


def _split(events: bytes) -> list[bytes]:
    return [events[k:k + 32] for k in range(0, len(events), 32)]


class ReadTest(unittest.TestCase):
    @needs("logic", "group-12.3.1.json")
    def test_groups_are_numbered_by_slot_with_members_from_the_objects(self):
        data = session(group_triple(4, 43, name="Room"), group_triple(0, 82, events=member_events(DEFAULT_FLAGS, KICK)),
                       numbers={KICK: 1, SNARE: 1, OH_L: 2}, registry=(0, 4))
        groups = read_groups(data)
        self.assertEqual([(g.number, g.slot, g.group_id, g.name, g.members) for g in groups],
                         [(1, 0, 82, "", (KICK, SNARE)), (2, 4, 43, "Room", (OH_L,))])
        self.assertEqual(groups[1].label, "Room")
        self.assertEqual(groups[0].label, "Group 1")
        self.assertEqual(group_of(data), {KICK: 1, SNARE: 1, OH_L: 2})

    def test_a_project_without_groups(self):
        self.assertEqual(read_groups(session()), [])
        self.assertEqual(group_errors(session()), [])


@needs("logic", "group-12.3.1.json")
class CreateTest(unittest.TestCase):
    def test_the_first_group_follows_the_rpyh_records(self):
        out, g = create_group(session(), name="OH", members=[OH_L, OH_R])
        self.assertEqual((g.number, g.slot, g.name, g.members, g.flags), (1, 0, "OH", (OH_L, OH_R), DEFAULT_FLAGS))
        t = tags(out)
        at = t.index(b"rpyH")
        self.assertEqual(t[at:at + 5], [b"rpyH", b"qeSM", b"karT", b"qSvE", b"ivnE"])
        self.assertEqual(events_of(out, 1), [(OH_L, 9), (OH_L, 7), (OH_R, 9), (OH_R, 7)])
        self.assertEqual(group_of(out), {OH_L: 1, OH_R: 1})
        self.assertEqual(group_errors(out), [])
        self.assertEqual(read_groups(out), [g])

    def test_the_record_carries_the_name_padded_and_the_flags_after_it(self):
        out, g = create_group(session(), name="Drums", settings=["Pan"])
        p = project_records(out)[g.start].raw[HEADER:]
        self.assertEqual(len(p), 297 + 6)
        self.assertEqual((struct.unpack_from("<H", p, 16)[0], p[18:24]), (5, b"Drums\x00"))
        self.assertEqual(struct.unpack_from("<I", p, 76)[0], flags_for(["Pan"]))
        self.assertEqual(project_records(out)[g.start].raw[6], 0x11)

    def test_the_registry_gets_a_pair_before_the_object_entries(self):
        out, _g = create_group(session(), members=[KICK])
        g = next(r.raw[HEADER:] for r in project_records(out) if r.tag == b"gnoS")
        for stride in (24, 16):
            entries = group_entries(g, stride)
            self.assertEqual([s for _at, s in entries], [0], stride)
            at = entries[0][0]
            self.assertEqual(struct.unpack_from("<II", g, at + stride), (0x14, KICK), stride)
            self.assertNotEqual(g[at + 8:at + stride], bytes(stride - 8), stride)

    def test_a_second_group_takes_the_next_slot_after_the_first(self):
        out, _ = create_group(session(), name="OH", members=[OH_L, OH_R])
        out, g = create_group(out, name="Drums", members=[KICK], settings=["Solo", "Pan"])
        self.assertEqual((g.number, g.slot), (2, 4))
        t = tags(out)
        at = t.index(b"rpyH")
        self.assertEqual(t[at:at + 8], [b"rpyH", b"qeSM", b"karT", b"qSvE", b"qeSM", b"karT", b"qSvE", b"ivnE"])
        self.assertEqual(events_of(out, 2), [(KICK, 3), (KICK, 10)])
        self.assertEqual(group_of(out), {OH_L: 1, OH_R: 1, KICK: 2})
        reg = next(r.raw[HEADER:] for r in project_records(out) if r.tag == b"gnoS")
        self.assertEqual([[s for _a, s in group_entries(reg, stride)] for stride in (24, 16)], [[0, 4], [0, 4]])
        self.assertEqual(group_errors(out), [])

    def test_the_ids_are_distinct_triple_ids(self):
        out, a = create_group(session(), members=[KICK])
        out, b = create_group(out, members=[SNARE])
        self.assertNotEqual(a.group_id, b.group_id)
        records = project_records(out)
        self.assertEqual(records[b.start + 2].owner, b.group_id)

    def test_a_member_moves_out_of_its_old_group(self):
        out, _ = create_group(session(), members=[KICK, SNARE])
        out, _ = create_group(out, members=[SNARE])
        self.assertEqual(events_of(out, 1), [(KICK, 9), (KICK, 7)])
        self.assertEqual(group_of(out), {KICK: 1, SNARE: 2})
        self.assertEqual(group_errors(out), [])

    def test_refusals(self):
        with self.assertRaises(ValueError):
            create_group(session(), members=[999])
        with self.assertRaises(ValueError):
            create_group(session(), name="Ré")
        with self.assertRaises(ValueError):
            create_group(session(), settings=["Loudness"])


@needs("logic", "group-12.3.1.json")
class AssignTest(unittest.TestCase):
    def setUp(self):
        self.data, _ = create_group(session(), name="OH", members=[OH_L])

    def test_joining_appends_the_members_events(self):
        out = assign(self.data, OH_R, 1)
        self.assertEqual(events_of(out, 1), [(OH_L, 9), (OH_L, 7), (OH_R, 9), (OH_R, 7)])
        self.assertEqual(group_of(out), {OH_L: 1, OH_R: 1})
        self.assertEqual(read_groups(out)[0].members, (OH_L, OH_R))
        self.assertEqual(group_errors(out), [])

    def test_leaving_drops_them_and_clears_the_number(self):
        out = assign(assign(self.data, OH_R, 1), OH_L, 0)
        self.assertEqual(events_of(out, 1), [(OH_R, 9), (OH_R, 7)])
        self.assertEqual(group_of(out), {OH_R: 1})
        self.assertEqual(group_errors(out), [])

    def test_moving_between_groups(self):
        out, _ = create_group(self.data, name="Room", members=[KICK])
        out = assign(out, OH_L, 2)
        self.assertEqual(events_of(out, 1), [])
        self.assertEqual(events_of(out, 2), [(KICK, 9), (KICK, 7), (OH_L, 9), (OH_L, 7)])
        self.assertEqual(group_of(out), {KICK: 2, OH_L: 2})

    def test_no_change_is_no_change(self):
        self.assertEqual(assign(self.data, OH_L, 1), self.data)
        self.assertEqual(assign(self.data, KICK, 0), self.data)

    def test_refusals(self):
        with self.assertRaises(ValueError):
            assign(self.data, OH_R, 3)
        with self.assertRaises(ValueError):
            assign(self.data, 999, 1)


@needs("logic", "group-12.3.1.json")
class SetGroupTest(unittest.TestCase):
    def setUp(self):
        self.data, _ = create_group(session(), members=[OH_L, OH_R])

    def test_rename_keeps_the_events_and_moves_the_flags(self):
        out = set_group(self.data, 1, name="Overheads")
        g = read_groups(out)[0]
        self.assertEqual((g.name, g.flags, g.members), ("Overheads", DEFAULT_FLAGS, (OH_L, OH_R)))
        self.assertEqual(events_of(out, 1), events_of(self.data, 1))

    def test_a_flag_only_box_leaves_the_events_alone(self):
        out = set_group(self.data, 1, settings=["Volume", "Mute", "Send 1", "Color"])
        self.assertEqual(set(read_groups(out)[0].settings), {"Volume", "Mute", "Send 1", "Color"})
        self.assertEqual(events_of(out, 1), events_of(self.data, 1))

    def test_a_fader_change_rewrites_every_members_events(self):
        out = set_group(self.data, 1, settings=["Mute", "Solo"])
        self.assertEqual(events_of(out, 1), [(OH_L, 9), (OH_L, 3), (OH_R, 9), (OH_R, 3)])
        self.assertEqual(group_errors(out), [])

    def test_refusals(self):
        with self.assertRaises(ValueError):
            set_group(self.data, 2, name="x")


class ErrorsTest(unittest.TestCase):
    def test_a_number_without_a_group(self):
        self.assertEqual(group_errors(session(numbers={KICK: 1})), ["object 88: in group 1, which does not exist"])

    def test_events_that_do_not_match_the_members(self):
        data = session(group_triple(0, 82), numbers={KICK: 1}, registry=(0,))
        self.assertEqual(group_errors(data), ["group 1: 0 event(s) for 1 member(s), 2 expected"])

    @needs("logic", "group-12.3.1.json")
    def test_a_slot_without_its_registry_pair(self):
        data = session(group_triple(0, 82, events=member_events(DEFAULT_FLAGS, KICK)), numbers={KICK: 1})
        self.assertEqual(group_errors(data), ["group 1: slot 0 has no registry entry"])


class RegisterGroupTest(unittest.TestCase):
    def test_entries_go_in_slot_order_and_a_filled_one_is_restamped(self):
        base = gnos(KICK, SNARE, groups=(0, 8))[HEADER:]
        out = register_group(base, slot=4, uuid=bytes(range(16)))
        for stride in (24, 16):
            self.assertEqual([s for _a, s in group_entries(out, stride)], [0, 4, 8], stride)
        again = register_group(out, slot=4, uuid=bytes(16))
        self.assertEqual(len(again), len(out))
        at = next(a for a, s in group_entries(again, 24) if s == 4)
        self.assertEqual(again[at + 8:at + 24], bytes(16))

    def test_object_entries_are_not_mistaken_for_group_entries(self):
        self.assertEqual(group_entries(gnos(KICK, SNARE)[HEADER:], 24), [])
