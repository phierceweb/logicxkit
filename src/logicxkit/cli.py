"""Unified logicxkit CLI — one entry point, one group per gear domain.

    logicxkit logic  <subcommand> [args]   # Logic strips (logicxkit.logic.cli)
    logicxkit au     <subcommand> [args]   # AU preset/state decoder (logicxkit.au.cli)
    logicxkit --version

A thin dispatcher: it peels the group name and forwards the rest to that subpackage's
(already-tested) CLI. New domains register by adding one line to GROUPS.
"""

from __future__ import annotations

import sys

from pf_core.log import get_logger, setup_logging

from logicxkit import __version__
from logicxkit.au import cli as _au_cli
from logicxkit.logic import cli as _logic_cli

GROUPS = {
    "logic": _logic_cli.main,
    "au": _au_cli.main,
}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # pf-core logging, adopted at the CLI boundary; the library imports only pf_core.utils
    # foundation helpers (atomic writes), never logging/exceptions.
    # Console stays clean (invocations log at debug); set LOG_FILE=... for a JSON-lines
    # audit trail of every run — useful since these tools mutate scenes loaded on live gear.
    setup_logging(app_logger_name="logicxkit")
    log = get_logger("logicxkit")

    if argv and argv[0] in ("-V", "--version"):
        print(f"logicxkit {__version__}")
        return 0
    if not argv or argv[0] in ("-h", "--help"):
        print("usage: logicxkit {" + "|".join(GROUPS) + "} <subcommand> [args]")
        print("  logicxkit logic --help   Logic channel-strip tools")
        print("  logicxkit au --help      AU preset/state decoder")
        print("  logicxkit --version      print the installed version")
        return 0
    group, rest = argv[0], argv[1:]
    if group not in GROUPS:
        print(f"logicxkit: unknown group {group!r} (expected {', '.join(GROUPS)})", file=sys.stderr)
        return 2

    log.debug("invoke", group=group, argv=rest)
    try:
        rc = GROUPS[group](rest)
    except Exception as e:  # library/validation errors -> clean stderr message; detail to file log
        log.debug("error", group=group, error=str(e), exc_info=True)
        print(f"logicxkit {group}: {e}", file=sys.stderr)
        return 1
    log.debug("done", group=group, rc=rc)
    return rc


if __name__ == "__main__":
    sys.exit(main())
