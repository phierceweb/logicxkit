"""Which session stack a template stack means: the one its header pairs with, else the one
unclaimed stack of its name; two of the name, or a header paired with a row that is no stack,
mean none."""

import unicodedata
import unittest

from logicxkit.logic.orchestrators.template_stacks import stack_targets
from logicxkit.logic.services.mixer.pairing import Pair
from logicxkit.logic.services.arrange.stacks import FOLDER, SUMMING, Stack


def row(object_id: int, name: str, label: str) -> dict:
    return {"object_id": object_id, "name": name, "label": label}


T = Stack(name="D", object_id=1, track_key=0, index=1, kind=FOLDER)
FOLDER_D = Stack(name="D", object_id=10, track_key=0, index=1, kind=FOLDER)
SUMMING_D = Stack(name="D", object_id=20, track_key=3, index=3, kind=SUMMING)


def header(session: dict | None) -> Pair:
    return Pair(row(1, "D", "Sub 1"), session, "object")


class StackTargetsTest(unittest.TestCase):
    def test_the_paired_header_wins_over_a_name_shared_by_two(self):
        got = stack_targets([header(row(20, "D", "Aux 3"))], [T], [FOLDER_D, SUMMING_D])
        self.assertIs(got[1], SUMMING_D)

    def test_two_of_the_name_and_no_paired_header_mean_neither(self):
        got = stack_targets([header(None)], [T], [FOLDER_D, SUMMING_D])
        self.assertEqual(got[1], "2 session stacks are named 'D' (Sub 1, Aux 3) and none pairs with the template's")

    def test_a_stack_another_header_claims_is_not_a_name_match(self):
        other = Stack(name="Kit", object_id=2, track_key=5, index=2, kind=FOLDER)
        pairs = [header(None), Pair(row(2, "Kit", "Sub 2"), row(20, "D", "Aux 3"), "object")]
        got = stack_targets(pairs, [T, other], [FOLDER_D, SUMMING_D])
        self.assertEqual((got[1], got[2]), (FOLDER_D, SUMMING_D))

    def test_a_header_paired_with_a_plain_track_means_no_stack(self):
        got = stack_targets([header(row(30, "D", "Aux 7"))], [T], [FOLDER_D])
        self.assertEqual(got[1], "its header pairs with D (Aux 7), which is not a stack")

    def test_no_stack_of_the_name(self):
        self.assertEqual(stack_targets([header(None)], [T], [])[1], "the stack does not exist yet")

    def test_names_compare_in_either_unicode_form(self):
        composed = Stack(name=unicodedata.normalize("NFC", "Bläser"), object_id=1, track_key=0, index=1)
        decomposed = Stack(name=unicodedata.normalize("NFD", "Bläser"), object_id=10, track_key=0, index=1)
        self.assertIs(stack_targets([], [composed], [decomposed])[1], decomposed)


if __name__ == "__main__":
    unittest.main()
