"""Picking a track by name, or by name and mixer label when a stack header shares it."""

import unittest

import _paths  # noqa: F401
from logicxkit.logic.services.arrange.trackname import one_object, rows_named, stack_named

ROWS = [
    {"object_id": 192, "name": "Drums MIDI", "label": "Sub 7"},
    {"object_id": 504, "name": "Drums MIDI", "label": "Inst 2"},
    {"object_id": 88, "name": "Kick In", "label": "Audio 1"},
    {"object_id": 90, "name": "Pad (dry)", "label": "Inst 3"},
]


class TrackNameTest(unittest.TestCase):
    def test_a_decomposed_argument_finds_a_composed_name(self):
        rows = [{"object_id": 88, "name": "Gitarre \u00fc", "label": "Audio 1"},
                {"object_id": 92, "name": None, "label": "Audio 2"}]
        self.assertEqual(one_object(rows, "Gitarre u\u0308"), 88)
        self.assertEqual(one_object(rows, "Gitarre u\u0308 (Audio 1)"), 88)
        self.assertEqual(rows_named(rows, "None"), [])

    def test_a_stack_is_found_in_either_unicode_form(self):
        from types import SimpleNamespace
        stacks = [SimpleNamespace(name="Drums"), SimpleNamespace(name="Bl\u00e4ser")]
        self.assertIs(stack_named(stacks, " Bla\u0308ser "), stacks[1])
        self.assertIsNone(stack_named(stacks, "Brass"))

    def test_two_stacks_of_one_name_need_the_strip(self):
        from types import SimpleNamespace
        stacks = [SimpleNamespace(name="Drums", strip="Sub 1"), SimpleNamespace(name="Drums", strip="Aux 9")]
        with self.assertRaisesRegex(ValueError, r"2 stacks named 'Drums'; say which: Drums \(Sub 1\), Drums \(Aux 9\)"):
            stack_named(stacks, "Drums")
        self.assertIs(stack_named(stacks, "Drums (Aux 9)"), stacks[1])
        self.assertIs(stack_named(stacks, "Drums (Sub 1)"), stacks[0])
        self.assertIsNone(stack_named(stacks, "Drums (Aux 2)"))

    def test_a_unique_name_needs_no_label(self):
        self.assertEqual(one_object(ROWS, "Kick In"), 88)

    def test_a_shared_name_is_refused_with_the_choices(self):
        with self.assertRaisesRegex(ValueError, r"2 tracks named 'Drums MIDI'; say which: Drums MIDI \(Sub 7\), Drums MIDI \(Inst 2\)"):
            one_object(ROWS, "Drums MIDI")

    def test_the_label_picks_the_row(self):
        self.assertEqual((one_object(ROWS, "Drums MIDI (Inst 2)"), one_object(ROWS, "Drums MIDI (Sub 7)")), (504, 192))

    def test_parentheses_that_are_not_a_label_stay_in_the_name(self):
        self.assertEqual(one_object(ROWS, "Pad (dry)"), 90)
        self.assertEqual(rows_named(ROWS, "Drums MIDI (Aux 9)"), [])

    def test_no_such_track(self):
        with self.assertRaisesRegex(ValueError, "no track named 'Nope'"):
            one_object(ROWS, "Nope")


if __name__ == "__main__":
    unittest.main()
