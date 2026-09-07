"""Unified logicxkit CLI dispatcher: routes groups, rejects unknowns.

Also the tilde: every documented example quotes its path, so a shell that never expanded `~`
would hand the tools a directory literally named `~`.
"""

import unittest
from argparse import Namespace
from pathlib import Path

from logicxkit.cli import main


class DispatchTest(unittest.TestCase):
    def test_help_no_args(self):
        self.assertEqual(main([]), 0)

    def test_unknown_group(self):
        self.assertEqual(main(["bogus"]), 2)


class VersionTest(unittest.TestCase):
    def test_version_flag_prints_and_exits_clean(self):
        import contextlib
        import io
        from logicxkit import __version__
        for flag in ("--version", "-V"):
            with self.subTest(flag):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    rc = main([flag])
                self.assertEqual(rc, 0)
                self.assertIn(__version__, buf.getvalue())

    def test_a_group_usage_line_is_a_runnable_command(self):
        """argparse derives prog from sys.argv[0], so a group that does not set it prints
        `usage: logicxkit ...` — a line that cannot be pasted back into a shell."""
        import contextlib
        import io
        for group in ("logic", "au"):
            with self.subTest(group):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf), contextlib.suppress(SystemExit):
                    main([group, "--help"])
                self.assertIn(f"usage: logicxkit {group}", buf.getvalue())


class TildeExpansionTest(unittest.TestCase):
    """`au` expanded its file argument; `logic` did not, so a quoted ~ path never resolved."""

    def test_logic_expands_every_path_argument(self):
        from logicxkit.logic.cli import _PATH_ARGS, _expand_paths
        args = Namespace(**{n: f"~/Music/{n}" for n in _PATH_ARGS})
        _expand_paths(args)
        for name in _PATH_ARGS:
            with self.subTest(name):
                self.assertEqual(getattr(args, name), str(Path.home() / "Music" / name))

    def test_a_path_without_a_tilde_is_untouched(self):
        from logicxkit.logic.cli import _expand_paths
        args = Namespace(project="out/x.logicx", out=None, spec=3)
        _expand_paths(args)
        self.assertEqual((args.project, args.out, args.spec), ("out/x.logicx", None, 3))

    def test_the_project_argument_reaches_the_command_expanded(self):
        """End to end: the error names the expanded path, so that is what was opened."""
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            with contextlib.suppress(SystemExit):
                main(["logic", "project", "~/Music/does-not-exist.logicx"])
        self.assertIn(str(Path.home() / "Music"), buf.getvalue())
        self.assertNotIn("~/Music", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
