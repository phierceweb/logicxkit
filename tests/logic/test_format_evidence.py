"""A capability row that names a file format beyond Logic 12.3.1's cites, in its catch, a public
corpus save of that format: a command opens on another Logic by evidence a clean clone can read."""

import json
import re
import unittest
from collections.abc import Callable

import _goldens

from logicxkit.logic import _capabilities
from logicxkit.logic._capability import Capability
from logicxkit.logic.services.stream.validate import MEASURED_FORMAT, file_format
from logicxkit.logicx import project_data

CITED = re.compile(r"`([a-z0-9][a-z0-9.\-]*)`")
LOGIC_11_2 = 2511


def public() -> dict:
    return json.loads(_goldens.PUBLIC.read_text())


def corpus_format(key: str) -> int | None:
    entry = public().get(key)
    bundle = _goldens.CORPUS / entry["path"] if entry and "path" in entry else None
    return file_format(project_data(bundle)) if bundle is not None and bundle.exists() else None


def unbacked(cap: Capability, keys: dict, format_of: Callable[[str], int | None]) -> list[int]:
    """The formats ``cap`` names beyond the measured one that no public save its catch cites is of."""
    cited = [k for k in CITED.findall(cap.catch) if k in keys]
    return [f for f in cap.formats if f != MEASURED_FORMAT and not any(format_of(k) == f for k in cited)]


def row(catch: str) -> Capability:
    return Capability(("probe",), "CONFIRMED", "yes", catch=catch, formats=(LOGIC_11_2, MEASURED_FORMAT))


class FormatEvidenceTest(unittest.TestCase):
    def test_every_row_that_opens_a_format_cites_a_public_save_of_it(self):
        keys = public()
        for cap in _capabilities.CAPABILITIES:
            with self.subTest(cap.commands[0]):
                self.assertEqual(unbacked(cap, keys, corpus_format), [],
                                 "name a public corpus save of each format the row opens, in backticks")


class TheCheckCanFailTest(unittest.TestCase):
    KEYS = {"probe-11-2-logic": {}, "probe-12-logic": {}}
    FORMATS = {"probe-11-2-logic": LOGIC_11_2, "probe-12-logic": MEASURED_FORMAT}.get

    def test_a_row_citing_nothing_is_unbacked(self):
        self.assertEqual(unbacked(row("opened on Logic 11.2"), self.KEYS, self.FORMATS), [LOGIC_11_2])

    def test_a_save_of_another_format_does_not_back_it(self):
        self.assertEqual(unbacked(row("as `probe-12-logic` shows"), self.KEYS, self.FORMATS), [LOGIC_11_2])

    def test_a_key_outside_the_public_corpus_does_not_back_it(self):
        self.assertEqual(unbacked(row("as `owner-11-2-logic` shows"), self.KEYS,
                                  lambda key: LOGIC_11_2), [LOGIC_11_2])

    def test_a_public_save_of_the_format_backs_it(self):
        self.assertEqual(unbacked(row("as `probe-11-2-logic` shows"), self.KEYS, self.FORMATS), [])

    def test_a_cited_key_is_read_from_the_corpus(self):
        self.assertEqual(corpus_format("blank-base"), MEASURED_FORMAT)
        self.assertIsNone(corpus_format("no-such-key"))


if __name__ == "__main__":
    unittest.main()
