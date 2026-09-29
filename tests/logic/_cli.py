"""Run a `logic` command in-process on a public corpus bundle and read back the bundle it wrote.

Every writer goes through `written`: exit 0, a bundle at ``out/<name>``, readable, and no
regression against its input — what the command layer itself has to guarantee before a test
looks at the command's own effect."""

from __future__ import annotations

import contextlib
import io
from pathlib import Path

import _goldens

from logicxkit.logic import cli
from logicxkit.logic._edit import first_project_data
from logicxkit.logic.services.integrity import regressions, structural_report
from logicxkit.logic.services.project import project_metadata
from logicxkit.logic.services.transplant import owner_of


def run(*argv) -> tuple[int, str]:
    """Exit code and output of `logic <argv>`; argparse's own exit is its code."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        try:
            code = cli.main([str(a) for a in argv])
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 2
    return code, buf.getvalue()


def wrapped(*argv) -> tuple[int, str]:
    """`logicxkit logic <argv>` through the top-level wrapper, which turns a library error into
    `logicxkit logic: <message>` and exit 1 — for a refusal a command lets propagate."""
    from logicxkit.cli import main as logicxkit_main
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        code = logicxkit_main(["logic", *[str(a) for a in argv]])
    return code, buf.getvalue()


def source(key: str | Path) -> Path:
    """A golden by key, or a bundle a test already wrote."""
    return key if isinstance(key, Path) else _goldens.path(key)


def written(test, command: str, key: str | Path, *rest, out: Path, copied: str | Path | None = None) -> Path:
    """Run ``command`` on the bundle into ``out``; the bundle it wrote, held to the input.
    ``copied`` names the bundle the command copies when that is not its first argument."""
    src = source(copied) if copied is not None else source(key)
    code, text = run(command, source(key), *rest, "--out", out)
    test.assertEqual(code, 0, text)
    dest = out / src.name
    test.assertTrue((dest / "Alternatives").is_dir(), f"no bundle at {dest}\n{text}")
    before, after = first_project_data(src), first_project_data(dest)
    test.assertIsNone(structural_report(after)["unreadable"], text)
    test.assertEqual(regressions(before, after), [], text)
    return dest


def data(bundle: str | Path) -> bytes:
    return first_project_data(source(bundle))


def count(bundle: str | Path) -> int | None:
    return project_metadata(source(bundle)).get("tracks")


def owner(bundle_data: bytes, label: str) -> int:
    found = owner_of(bundle_data, label)
    assert found is not None, f"no channel labelled {label!r}"
    return found
