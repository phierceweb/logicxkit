"""Put tests/ on sys.path so subdirectories can import the shared helpers, refuse any read of
Logic's live library (`_liveguard`), and say at the end which goldens the run could and could
not find (`_goldens`)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "logic"))     # _records, _invariants, _fixtures for tests/goldens too


def pytest_configure(config):
    import _liveguard
    _liveguard.install()


def pytest_terminal_summary(terminalreporter):
    import _goldens
    import _liveguard
    line = _goldens.report()
    if line:
        terminalreporter.write_sep("-", line)
    if _liveguard.violations:
        raise AssertionError("read Logic's live library: " + ", ".join(sorted(set(_liveguard.violations))))
