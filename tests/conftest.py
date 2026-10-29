"""Put tests/ on sys.path so subdirectories can import the shared helpers, drop bytecode that
disagrees with its source (`_bytecode`), refuse any read of Logic's live library (`_liveguard`),
and say at the end which goldens the run could and could not find (`_goldens`) and whether the
swift toolchain was there for the tests that need it."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "logic"))     # _records, _invariants, _fixtures for tests/goldens too

_ROOT = Path(__file__).resolve().parents[1]
_PURGED = ("src", "tests")             # a stale test cache runs an old assertion, same as an old rule


def pytest_configure(config):
    """Bytecode compiled from a source this tree no longer holds is removed before collection."""
    import _bytecode
    import _liveguard
    _liveguard.install()
    removed = [p for root in _PURGED for p in _bytecode.purge(_ROOT / root)]
    if removed:
        print(f"\nremoved {len(removed)} stale bytecode cache(s): "
              + ", ".join(p.name for p in removed[:5]), file=sys.stderr)


def pytest_terminal_summary(terminalreporter):
    import _goldens
    import _liveguard
    line = _goldens.report()
    if line:
        terminalreporter.write_sep("-", line)
    from logicxkit.utils.swiftrun import swift_available
    if not swift_available():
        terminalreporter.write_sep("-", "swift: absent; every test that runs a swift helper skipped")
    if _liveguard.violations:
        raise AssertionError("read Logic's live library: " + ", ".join(sorted(set(_liveguard.violations))))
