"""A MIDI split leaves both pieces holding the parent's events; the `midi` and `regions` listings say
how many the region plays when that differs, and `--json` carries `played`."""

import contextlib
import io
import json
import unittest

import _goldens
from logicxkit.cli import main
from logicxkit.logic.services.midi.midi import read_midi
from logicxkit.logicx import project_data

SPLIT, TWO = "regions-a10-midi-split-logic", "midi-two-notes-logic"


def run(*argv) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        rc = main(["logic", *map(str, argv)])
    return rc, buf.getvalue()


@_goldens.needs(SPLIT, TWO)
class PlayedTest(unittest.TestCase):
    def test_the_listings_say_held_and_played_when_they_differ(self):
        regions = read_midi(project_data(_goldens.path(SPLIT)))
        differ = [r for r in regions if len(r.played) != len(r.events)]
        self.assertTrue(differ)
        for command in ("midi", "regions"):
            rc, text = run(command, _goldens.path(SPLIT))
            self.assertEqual(rc, 0, text)
            for r in regions:
                with self.subTest(command=command, region=r.name):
                    said = f"{len(r.events)} event(s), {len(r.played)} played" if r in differ else f"{len(r.events)} event(s)"
                    self.assertIn(said, text)
            self.assertNotIn(", 2 played", run(command, _goldens.path(TWO))[1])

    def test_json_carries_played(self):
        rc, text = run("midi", _goldens.path(SPLIT), "--json")
        self.assertEqual(rc, 0, text)
        regions = read_midi(project_data(_goldens.path(SPLIT)))
        for row, r in zip(json.loads(text), regions, strict=True):
            self.assertEqual((len(row["events"]), len(row["played"])), (len(r.events), len(r.played)))
            self.assertEqual([e["tick"] for e in row["played"]], [e.tick for e in r.played])
        rc, text = run("regions", _goldens.path(SPLIT), "--json")
        self.assertEqual([(m["events"], m["played"]) for m in json.loads(text)["midi"]],
                         [(len(r.events), len(r.played)) for r in regions])


if __name__ == "__main__":
    unittest.main()
