"""Track stacks and the arrange track list.

`karT` rows (key = display order, +8 = object id, +0 flags, +14 = inside-a-stack), `ivnE`
objects (names), and the `OCuA` channels each row is bound to. A stack is a grouping object
bound to a `Sub N` strip; its members are the rows below it whose +14 byte is set."""

import unittest
from _records import chan, env_obj, marker, proj, track, uuid
from logicxkit.logic.services.stacks import (
    FOLDER,
    HIDDEN_BIT,
    HIDDEN_FLAG,
    arrange_list,
    move_to_stack,
    read_stacks,
    read_tracks,
    stack_parents,
    track_lists,
)


def session(*extra: bytes) -> bytes:
    """Drums(Sub 1){Kick In, Snare Up}  Bass(Sub 2){Bass MIDI, Bass DI}  Drums aux, Room, Master."""
    return proj(
        env_obj(192, "Drums", grouping=True), env_obj(88, "Kick In"), env_obj(92, "Snare Up"),
        env_obj(196, "Bass", grouping=True), env_obj(416, "Bass MIDI"), env_obj(152, "Bass DI"),
        env_obj(212, "Drums"), env_obj(180, "Room", grouping=True),
        env_obj(80, "Master", grouping=True),
        chan(378, "Sub 1", uuid=uuid(192)), chan(0, "Audio 1", uuid=uuid(88), stack_index=1),
        chan(2, "Audio 3", uuid=uuid(92), stack_index=1),
        chan(379, "Sub 2", uuid=uuid(196)), chan(87, "Inst 3", uuid=uuid(416), stack_index=2),
        chan(16, "Audio 17", uuid=uuid(152), stack_index=2),
        chan(68, "Aux 2", uuid=uuid(212)), chan(84, "Aux 18", uuid=uuid(180)),
        chan(401, "Output 1-2", uuid=uuid(80), size=201),
        *extra,
        track(0, 192), track(1, 88, member=True), track(2, 92, member=True), track(3, 196),
        track(4, 416, member=True), track(5, 152, member=True), track(6, 212), track(7, 180),
        track(8, 80, flag=3))

TRACKS = 8


class TrackListTest(unittest.TestCase):
    def test_zero_size_records_split_the_lists(self):
        data = proj(track(0, 88), marker(), track(0, 92), track(1, 96), marker())
        self.assertEqual([len(run) for run in track_lists(data)], [1, 2])

    def test_arrange_list_is_picked_by_track_count(self):
        data = proj(track(0, 88), marker(), track(0, 92), track(1, 96), marker())
        self.assertEqual(len(arrange_list(data, track_count=1)), 2)

    def test_names_resolve_through_the_environment(self):
        rows = read_tracks(session(), TRACKS)
        self.assertEqual(rows[1]["name"], "Kick In")

    def test_rows_carry_their_bound_channel(self):
        rows = read_tracks(session(), TRACKS)
        self.assertEqual((rows[1]["owner"], rows[1]["label"], rows[1]["stack_index"]),
                         (0, "Audio 1", 1))
        self.assertEqual(rows[0]["label"], "Sub 1")

    def test_hidden_is_a_bit_not_a_value(self):
        data = proj(env_obj(88, "Rack 1"), env_obj(92, "Floor 2"), env_obj(96, "Rack 2"),
                    track(0, 88, flag=HIDDEN_FLAG), track(1, 92, flag=0x241C0001), track(2, 96))
        self.assertEqual([r["hidden"] for r in read_tracks(data, 2)], [True, True, False])
        self.assertTrue(HIDDEN_FLAG & HIDDEN_BIT)


class StackTest(unittest.TestCase):
    def test_only_sub_bound_grouping_objects_are_stacks(self):
        self.assertEqual([s.name for s in read_stacks(session(), TRACKS)], ["Drums", "Bass"])

    def test_stack_knows_its_sub_channel(self):
        drums = read_stacks(session(), TRACKS)[0]
        self.assertEqual((drums.index, drums.owner, drums.kind), (1, 378, FOLDER))

    def test_members_follow_their_stack(self):
        stacks = read_stacks(session(), TRACKS)
        self.assertEqual([n for _k, n in stacks[0].members], ["Kick In", "Snare Up"])

    def test_an_instrument_row_is_a_member(self):
        stacks = read_stacks(session(), TRACKS)
        self.assertEqual([n for _k, n in stacks[1].members], ["Bass MIDI", "Bass DI"])

    def test_the_member_byte_ends_the_span(self):
        """`Drums` (Aux 2) follows Bass's members with +14 == 0: the stack ends there."""
        stacks = read_stacks(session(), TRACKS)
        self.assertNotIn("Drums", [n for _k, n in stacks[1].members])
        self.assertNotIn("Master", [n for _k, n in stacks[1].members])

    def test_membership_does_not_need_a_stack_index(self):
        """The Click and trigger-aux rows inside Drums MIDI carry stack index 0 but +14 == 1;
        a top-level instrument track right after a stack carries +14 == 0."""
        data = proj(
            env_obj(272, "Drums MIDI", grouping=True), env_obj(264, "Click"),
            env_obj(208, "Hi Hat MIDI"), env_obj(504, "Test Bounce"),
            chan(384, "Sub 7", uuid=uuid(272)), chan(85, "Inst 1", uuid=uuid(264)),
            chan(67, "Aux 1", uuid=uuid(208)), chan(88, "Inst 4", uuid=uuid(504)),
            track(0, 272), track(1, 264, member=True), track(2, 208, member=True),
            track(3, 504))
        stacks = read_stacks(data, 3)
        self.assertEqual([n for _k, n in stacks[0].members], ["Click", "Hi Hat MIDI"])

    def test_rows_report_member_and_expanded(self):
        rows = read_tracks(session(), TRACKS)
        self.assertEqual([r["member"] for r in rows[:4]], [False, True, True, False])
        self.assertFalse(rows[0]["expanded"])


class MoveToStackTest(unittest.TestCase):
    """A real drag moves the row, stamps `ivnE+38`, and sets `+110` on the bound channel."""

    def test_the_row_moves_into_the_stacks_span(self):
        out = move_to_stack(session(), 152, 192, track_count=TRACKS)
        found = {s.name: [n for _k, n in s.members] for s in read_stacks(out, TRACKS)}
        self.assertEqual(found["Drums"], ["Kick In", "Snare Up", "Bass DI"])
        self.assertEqual(found["Bass"], ["Bass MIDI"])

    def test_a_top_level_track_becomes_a_member(self):
        """A row that was top level (+14 == 0) gets the byte set when dragged in."""
        out = move_to_stack(session(), 212, 196, track_count=TRACKS)   # the Drums aux -> Bass
        row = next(r for r in read_tracks(out, TRACKS) if r["name"] == "Drums" and r["label"] == "Aux 2")
        self.assertTrue(row["member"])

    def test_the_parent_pointer_is_stamped_as_u32(self):
        out = move_to_stack(session(), 152, 192, track_count=TRACKS)
        self.assertEqual(stack_parents(out).get(152), 192)

    def test_the_channel_stack_index_follows(self):
        from logicxkit.logic.services.binding import channels
        out = move_to_stack(session(), 152, 192, track_count=TRACKS)
        self.assertEqual(channels(out)[16].stack_index, 1)

    def test_keys_stay_the_display_order(self):
        out = move_to_stack(session(), 152, 192, track_count=TRACKS)
        keys = [r["key"] for r in read_tracks(out, TRACKS)]
        self.assertEqual(keys, list(range(len(keys))))

    def test_a_track_already_in_the_stack_is_untouched(self):
        data = session()
        self.assertEqual(move_to_stack(data, 88, 192, track_count=TRACKS), data)

    def test_refuses_a_target_that_is_not_a_stack(self):
        with self.assertRaises(ValueError):
            move_to_stack(session(), 152, 180, track_count=TRACKS)   # Room is an aux

    def test_refuses_a_track_that_is_not_in_the_list(self):
        with self.assertRaises(ValueError):
            move_to_stack(session(), 9999, 192, track_count=TRACKS)

    def test_the_project_length_is_unchanged(self):
        data = session()
        self.assertEqual(len(move_to_stack(data, 152, 192, track_count=TRACKS)), len(data))

    def test_a_corrupt_stream_is_refused(self):
        data = session() + b"\x00" * 5          # a tail the walk cannot consume
        with self.assertRaises(ValueError):
            move_to_stack(data, 152, 192, track_count=TRACKS)


class HideTest(unittest.TestCase):
    def test_the_bit_flips_and_nothing_else_moves(self):
        from logicxkit.logic.services.stacks import set_hidden
        data = session()
        out = set_hidden(data, 152, True, track_count=TRACKS)
        rows = {r["object_id"]: r for r in read_tracks(out, TRACKS)}
        self.assertTrue(rows[152]["hidden"])
        self.assertEqual([r["hidden"] for oid, r in rows.items() if oid != 152],
                         [r["hidden"] for oid, r in {r["object_id"]: r for r in read_tracks(data, TRACKS)}.items() if oid != 152])
        self.assertEqual(len(out), len(data))
        back = set_hidden(out, 152, False, track_count=TRACKS)
        self.assertEqual(back, data)

    def test_refuses_an_object_off_the_list(self):
        from logicxkit.logic.services.stacks import set_hidden
        with self.assertRaises(ValueError):
            set_hidden(session(), 999, True, track_count=TRACKS)


class PowerTest(unittest.TestCase):
    """The track's power button is the row's 0x20000000 bit: Logic's own save of one click
    (goldens `power-off` -> `power-on`) flipped it and nothing else on the track."""

    def test_the_bit_round_trips_and_the_row_reads_it(self):
        from _records import chan, env_obj, marker, proj, track, uuid
        from logicxkit.logic.services.stacks import read_tracks, set_power
        from logicxkit.logic.services.tracklist import OFF_BIT
        data = proj(env_obj(88, "Gtr 1 DI"), env_obj(80, "Master", grouping=True),
                    chan(0, "Audio 1", uuid=uuid(88)), chan(402, "Output 1-2", uuid=uuid(80), size=201),
                    track(0, 88), track(1, 80, flag=3), marker())
        self.assertTrue(read_tracks(data, 2)[0]["on"])
        off = set_power(data, 88, False, track_count=2)
        row = read_tracks(off, 2)[0]
        self.assertEqual((row["on"], row["flag"] & OFF_BIT), (False, OFF_BIT))
        self.assertEqual(set_power(off, 88, True, track_count=2), data)
        with self.assertRaises(ValueError):
            set_power(data, 999, False, track_count=2)
