"""Every string argument of `logicxkit logic` is classified as a path, which expands a quoted
`~`, or as not one. A new argument fails here until it is put in one list or the other."""

import argparse
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

from logicxkit.logic import cli

NOT_PATHS = {
    "add", "after", "assign", "by", "channel", "copy", "create", "hide", "input", "key", "key_at",
    "length", "mono", "move", "name", "output", "pane", "ramp", "remove", "rename", "row", "set",
    "audio", "note", "patch", "region", "setting", "show", "skip", "stack", "stereo", "time", "time_at", "track",
    "ref", "group", "off", "edits", "drum_map", "hit", "id", "category", "meter",
    "tempo", "intensity", "role", "unmapped", "select", "steps", "seed", "velocity", "clear",
    "plugin", "as_name", "side_chain", "source", "target", "bypass", "fader", "mode", "pan", "move_out",
    "flatten", "convert"}


def _string_dests() -> set[str]:
    captured = {}

    def grab(self, *_a, **_k):
        captured.setdefault("parser", self)
        raise SystemExit(0)

    with mock.patch.object(argparse.ArgumentParser, "parse_args", grab), \
         mock.patch("builtins.print"):
        try:
            cli.main([])
        except SystemExit:
            pass
    flags = (argparse._HelpAction, argparse._StoreTrueAction, argparse._StoreFalseAction,
             argparse._StoreConstAction, argparse._CountAction)

    def dests(parser) -> set[str]:
        found = set()
        for a in parser._actions:
            if isinstance(a, argparse._SubParsersAction):
                found |= {d for p in a.choices.values() for d in dests(p)}
            elif not isinstance(a, flags) and a.type in (None, str) and a.dest not in ("help", "func"):
                found.add(a.dest)
        return found

    return dests(captured["parser"])


class PathArgsTest(unittest.TestCase):
    def test_every_string_argument_is_classified(self):
        self.assertEqual(sorted(_string_dests() - set(cli._PATH_ARGS) - NOT_PATHS), [])

    def test_a_quoted_tilde_expands_in_a_single_path_and_a_list_of_them(self):
        args = Namespace(template="~/t.logicx", src="~/s.logicx", baseline=["~/x", "~/y"],
                         track=["~Name"])
        cli._expand_paths(args)
        home = str(Path.home())
        self.assertEqual((args.template, args.src), (f"{home}/t.logicx", f"{home}/s.logicx"))
        self.assertEqual(args.baseline, [f"{home}/x", f"{home}/y"])
        self.assertEqual(args.track, ["~Name"])


if __name__ == "__main__":
    unittest.main()
