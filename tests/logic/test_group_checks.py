"""Group problems the gate names, the registry's group entries, and the listing of a member whose name
does not decode."""

import unittest

from _records import env_obj, gnos, group_triple, proj
from _data import needs
from logic.test_groups import KICK, SNARE, session

from logicxkit.logic.services.arrange.groups import (
    DEFAULT_FLAGS, group_errors, missing_group_events,
)
from logicxkit.logic.services.arrange.groups_write import member_events
from logicxkit.logic.services.stream.stream import HEADER
from logicxkit.logic.services.stream.registry import group_entries, register_group


class ErrorsTest(unittest.TestCase):
    def test_a_number_without_a_group(self):
        self.assertEqual(group_errors(session(numbers={KICK: 1})), ["object 88: in group 1, which does not exist"])
        self.assertEqual(group_errors(session(numbers={KICK: 0b100})), ["object 88: in group 3, which does not exist"])

    @needs("logic", "group-12.3.1.json")
    def test_only_the_missing_group_of_a_channels_bits_is_reported(self):
        data = session(group_triple(0, 82, events=member_events(DEFAULT_FLAGS, KICK)), numbers={KICK: 0b101},
                       registry=(0,))
        self.assertEqual(group_errors(data), ["object 88: in group 3, which does not exist"])

    def test_a_group_with_no_events_is_no_error(self):
        """Logic's own saves lack them on a switched-off group, and some of a live one's."""
        data = session(group_triple(0, 82), numbers={KICK: 1}, registry=(0,))
        self.assertEqual(group_errors(data), [])

    @needs("logic", "group-12.3.1.json")
    def test_missing_events_are_counted_apart_from_the_errors(self):
        both = member_events(DEFAULT_FLAGS, KICK) + member_events(DEFAULT_FLAGS, SNARE)
        whole = session(group_triple(0, 82, events=both), numbers={KICK: 1, SNARE: 1}, registry=(0,))
        less = session(group_triple(0, 82, events=member_events(DEFAULT_FLAGS, KICK)), numbers={KICK: 1, SNARE: 1},
                       registry=(0,))
        self.assertEqual((missing_group_events(whole), missing_group_events(less)), (0, 2))
        self.assertEqual(group_errors(less), [])

    @needs("logic", "group-12.3.1.json")
    def test_an_event_for_a_track_the_group_does_not_hold_or_a_repeated_one(self):
        both = member_events(DEFAULT_FLAGS, KICK) + member_events(DEFAULT_FLAGS, SNARE)
        data = session(group_triple(0, 82, events=both), numbers={KICK: 1}, registry=(0,))
        self.assertEqual(group_errors(data), ["group 1: 2 event(s) for a track or a fader it does not link, or repeated"])
        twice = member_events(DEFAULT_FLAGS, KICK) * 2
        data = session(group_triple(0, 82, events=twice), numbers={KICK: 1}, registry=(0,))
        self.assertEqual(group_errors(data), ["group 1: 2 event(s) for a track or a fader it does not link, or repeated"])

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


class ListingTest(unittest.TestCase):
    def test_a_member_whose_name_does_not_decode_is_listed_by_its_id(self):
        import io
        from contextlib import redirect_stdout

        from logicxkit.logic._groups import _print
        from logicxkit.logic.services.arrange.environment import channel_objects
        from logicxkit.logic.services.arrange.groups import Group
        objs = channel_objects(proj(env_obj(500, b"Gitarre \xfc")))
        out = io.StringIO()
        with redirect_stdout(out):
            _print([Group(1, 0, 1, "Drums", DEFAULT_FLAGS, (500,), 0)], objs)
        self.assertIn("500", out.getvalue())


if __name__ == "__main__":
    unittest.main()
