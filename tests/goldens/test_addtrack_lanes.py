"""A track added beside tracks that carry lanes, held to Logic's own New Audio Track on the same
project: the rows Logic makes, and every lane where it was, the new track's automation folder its
closing event alone. Skips without the public corpus."""

import unittest

import _goldens

from logicxkit.logic.services.arrange.addtrack import add_track
from logicxkit.logic.services.arrange.stacks import read_tracks
from logicxkit.logic.services.project.project import project_metadata
from logicxkit.logic.services.regions.automation import read_automation
from logicxkit.logicx import project_data

BEFORE, ADDED = "addtrack-lanes-before-logic", "addtrack-lanes-after-logic"


def reading(data: bytes, count: int) -> tuple[list, list]:
    rows = [(r["name"], r["label"]) for r in read_tracks(data, count)]
    lanes = sorted((a.track or "", ln.parameter, tuple((p.tick, p.value) for p in ln.points))
                   for a in read_automation(data, count) for ln in a.lanes)
    return rows, lanes


@_goldens.needs(BEFORE, ADDED)
class AddBesideLanesTest(unittest.TestCase):
    def test_the_new_track_reads_no_lanes_as_logics_own(self):
        base, count = project_data(_goldens.path(BEFORE)), project_metadata(_goldens.path(BEFORE))["tracks"]
        after = next(r["object_id"] for r in read_tracks(base, count) if r["name"] == _goldens.fact(ADDED, "after"))
        ours, report = add_track(base, name=_goldens.fact(ADDED, "added"), after=after, track_count=count)
        logics = project_data(_goldens.path(ADDED))
        self.assertEqual(reading(ours, count + 1), reading(logics, project_metadata(_goldens.path(ADDED))["tracks"]))
        self.assertEqual({a.track for a in read_automation(logics) if a.lanes},
                         set(_goldens.fact(BEFORE, "lanes")))


if __name__ == "__main__":
    unittest.main()
