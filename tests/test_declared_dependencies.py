"""What `pyproject.toml` pins must be what is installed.

`pip check` reads the *installed* logicxkit metadata, so an editable install keeps answering for
the pin it was built with: `pyproject.toml` can move to a version that does not exist anywhere and
`pip check` still reports "No broken requirements found" while the suite runs green against a
source tree whose distribution says otherwise.

This reads the pins from the file rather than from metadata, so it cannot be fooled the same way.
It does not reach the network: an unpublished version is caught here only when the venv does not
hold it either, which is the case that matters — the tree is being tested against something no
fresh install can obtain.
"""

import tomllib
import unittest
from importlib.metadata import PackageNotFoundError, version

from packaging.requirements import Requirement

from _paths import REPO

PYPROJECT = REPO / "pyproject.toml"


def declared() -> list[Requirement]:
    """The hard runtime dependencies, as `pyproject.toml` writes them. Optional extras are left
    out: `rig` is deliberately absent on most machines."""
    project = tomllib.loads(PYPROJECT.read_text())["project"]
    return [Requirement(d) for d in project["dependencies"]]


class DeclaredDependencyTest(unittest.TestCase):
    def test_every_pin_is_satisfied_by_what_is_installed(self):
        wrong = []
        for req in declared():
            try:
                have = version(req.name)
            except PackageNotFoundError:
                wrong.append(f"{req}: not installed")
                continue
            if not req.specifier.contains(have, prereleases=True):
                wrong.append(f"{req}: installed {have}")
        self.assertEqual(wrong, [], "pyproject.toml pins a version this venv does not hold, so a "
                                    "fresh install resolves differently from this run — publish "
                                    "the dependency or correct the pin, then `bin/run setup`")

    def test_the_pins_are_read_from_the_file_and_there_are_some(self):
        """A parse that quietly yielded nothing would pass the check above for the wrong reason."""
        names = [r.name for r in declared()]
        self.assertIn("groovebin", names)
        self.assertTrue(all(str(r.specifier) for r in declared()),
                        f"an unpinned runtime dependency: {[str(r) for r in declared()]}")


if __name__ == "__main__":
    unittest.main()
