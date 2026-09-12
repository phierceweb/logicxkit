"""The end-of-run goldens line: the count always, the key names only when they help."""

import os
import unittest
from contextlib import contextmanager
from unittest import mock

import _goldens


@contextmanager
def asked(found: int, missing: int):
    keys = {f"found-{i}": True for i in range(found)}
    keys |= {f"missing-{i:02d}": False for i in range(missing)}
    # An ambient LOGICXKIT_REQUIRE_GOLDENS would make every report() here raise.
    with mock.patch.dict(_goldens.asked, keys, clear=True), mock.patch.dict(os.environ):
        os.environ.pop(_goldens.REQUIRE, None)
        yield


class ReportTest(unittest.TestCase):
    def test_no_keys_asked_reports_nothing(self):
        with asked(0, 0):
            self.assertIsNone(_goldens.report())

    def test_a_full_corpus_names_no_keys(self):
        with asked(73, 0):
            self.assertEqual(_goldens.report(), "goldens: 73 of 73 keys found")

    def test_a_checkout_without_the_corpus_lists_none_of_them(self):
        with asked(0, 73):
            line = _goldens.report()
        self.assertEqual(line, "goldens: 0 of 73 keys found; none on this machine")
        self.assertNotIn("missing-00", line)

    def test_a_few_missing_are_all_named(self):
        with asked(70, 3):
            line = _goldens.report()
        self.assertEqual(
            line, "goldens: 70 of 73 keys found; missing: missing-00, missing-01, missing-02")

    def test_many_missing_are_truncated_with_a_count(self):
        with asked(40, 33):
            line = _goldens.report()
        self.assertIn("goldens: 40 of 73 keys found; missing: missing-00", line)
        self.assertTrue(line.endswith(f"(+{33 - _goldens.MISSING_SHOWN} more)"), line)
        self.assertEqual(line.count("missing-"), _goldens.MISSING_SHOWN)

    def test_the_require_env_fails_with_every_name(self):
        with asked(40, 33), mock.patch.dict("os.environ", {_goldens.REQUIRE: "1"}):
            with self.assertRaises(AssertionError) as caught:
                _goldens.report()
        message = str(caught.exception)
        self.assertNotIn("more)", message)
        for i in range(33):
            self.assertIn(f"missing-{i:02d}", message)

    def test_the_ci_grep_still_matches_every_shape(self):
        for found, missing in ((73, 0), (0, 73), (70, 3), (40, 33)):
            with self.subTest(found=found, missing=missing), asked(found, missing):
                self.assertRegex(_goldens.report(), r"goldens: \d+ of \d+ keys found")


if __name__ == "__main__":
    unittest.main()
