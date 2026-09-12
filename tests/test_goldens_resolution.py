"""A golden key resolves to the public corpus first and the owner's files second, and its
facts come from whichever manifest supplied the file."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _goldens


def _bundle(root: Path, rel: str) -> None:
    (root / rel / "Alternatives" / "000").mkdir(parents=True)
    (root / rel / "Alternatives" / "000" / "ProjectData").write_bytes(b"x")


class ResolutionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.public = self.root / "public.json"
        self.owner = self.root / "experiments" / "manifest.json"
        self.owner.parent.mkdir()
        # The tally and the steering env vars belong to the whole run, not to these tests.
        self.enterContext(mock.patch.dict(_goldens.asked, {}, clear=True))
        self.enterContext(mock.patch.dict(os.environ))
        for var in (_goldens.REQUIRE, "LOGICXKIT_GOLDENS"):
            os.environ.pop(var, None)
        self.saved = (_goldens.RESOURCES, _goldens.MANIFEST, _goldens.PUBLIC)
        _goldens.RESOURCES, _goldens.MANIFEST, _goldens.PUBLIC = self.root, self.owner, self.public
        _goldens.reset()

    def tearDown(self):
        _goldens.RESOURCES, _goldens.MANIFEST, _goldens.PUBLIC = self.saved
        _goldens.reset()
        self.tmp.cleanup()

    def _write(self, public: dict, owner: dict) -> None:
        self.public.write_text(json.dumps(public))
        self.owner.write_text(json.dumps(owner))

    def test_public_wins_when_its_file_is_there(self):
        _bundle(self.root, "public/a.logicx")
        _bundle(self.root, "experiments/9-a.logicx")
        self._write({"k": {"path": "public/a.logicx", "facts": {"on": ["Cycle"]}}},
                    {"k": {"path": "experiments/9-a.logicx", "facts": {"on": ["Solo"]}}})
        self.assertEqual(_goldens.path("k"), self.root / "public/a.logicx")
        self.assertEqual(_goldens.fact("k", "on"), ["Cycle"])

    def test_owner_is_the_fallback_when_the_public_file_is_absent(self):
        _bundle(self.root, "experiments/9-a.logicx")
        self._write({"k": {"path": "public/a.logicx", "facts": {"on": ["Cycle"]}}},
                    {"k": {"path": "experiments/9-a.logicx", "facts": {"on": ["Solo"]}}})
        self.assertEqual(_goldens.path("k"), self.root / "experiments/9-a.logicx")
        self.assertEqual(_goldens.fact("k", "on"), ["Solo"])

    def test_a_key_only_the_owner_has_still_resolves(self):
        _bundle(self.root, "experiments/song.logicx")
        self._write({}, {"song": {"path": "experiments/song.logicx"}})
        self.assertEqual(_goldens.path("song"), self.root / "experiments/song.logicx")

    def test_no_manifest_at_all_means_nothing_found(self):
        self.assertIsNone(_goldens.path("k"))
        self.assertIn("0 of 1", _goldens.report())


if __name__ == "__main__":
    unittest.main()


class CorpusSwitchTest(ResolutionTest):
    def test_owner_first_when_asked(self):
        _bundle(self.root, "public/a.logicx")
        _bundle(self.root, "experiments/9-a.logicx")
        self._write({"k": {"path": "public/a.logicx", "facts": {"on": ["Cycle"]}}},
                    {"k": {"path": "experiments/9-a.logicx", "facts": {"on": ["Solo"]}}})
        os.environ["LOGICXKIT_GOLDENS"] = "owner"
        _goldens.reset()
        self.assertEqual(_goldens.path("k"), self.root / "experiments/9-a.logicx")


class RequirePublicTest(ResolutionTest):
    """`LOGICXKIT_REQUIRE_GOLDENS=public`: a key the public manifest names must resolve; a key
    only the owner's manifest names may still skip."""

    def _run(self, public, owner):
        self._write(public, owner)
        os.environ[_goldens.REQUIRE] = "public"
        _goldens.reset()
        for k in set(public) | set(owner):
            _goldens.path(k)
        return _goldens.report()

    def test_a_missing_public_key_fails(self):
        with self.assertRaises(AssertionError):
            self._run({"k": {"path": "public/gone.logicx"}}, {})

    def test_a_missing_owner_only_key_still_skips(self):
        _bundle(self.root, "public/a.logicx")
        line = self._run({"k": {"path": "public/a.logicx"}}, {"song": {"path": "experiments/song.logicx"}})
        self.assertIn("1 of 2", line)
