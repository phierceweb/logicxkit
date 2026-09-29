"""A failed op's reason: the first line of the error that names a problem."""

import unittest

from logicxkit.logic.orchestrators.ops import _reason


class ReasonTest(unittest.TestCase):
    def test_a_gates_heading_line_is_skipped_for_the_problem_under_it(self):
        e = ValueError("refusing to write — the edit broke structure the input had right:\n"
                       "  sequence link errors 0 -> 5\n  1 channel(s) whose key flags no longer match")
        self.assertEqual(_reason(e), "sequence link errors 0 -> 5")

    def test_a_plain_message_is_itself(self):
        self.assertEqual(_reason(ValueError("no channel labelled 'Audio 9'")), "no channel labelled 'Audio 9'")

    def test_only_heading_lines_fall_back_to_the_first(self):
        self.assertEqual(_reason(ValueError("refusing: output overlaps the input")), "refusing: output overlaps the input")
        self.assertEqual(_reason(ValueError("")), "")


if __name__ == "__main__":
    unittest.main()
