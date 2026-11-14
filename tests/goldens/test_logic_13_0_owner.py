"""Logic 13.0's re-saves of the owner's sessions, staged as `<key>-13-0` beside the originals and Logic
12.4's `<key>-12-4`: each reads as the original through every reader but the arrange rows, where 13.0
writes a row the original listed twice once (Logic's own track count drops by as many), and validates
clean; its groups keep every event the original had, where 12.4 had dropped the Volume ones. Skips
where the owner's sessions are absent."""

import json
import unittest
from collections import Counter

import _goldens

from logicxkit.logic.services.arrange.groups import FADER_IDS, group_errors
from logicxkit.logic.services.project.project import project_metadata
from logicxkit.logic.services.stream.validate import file_format, validate_project
from logicxkit.logicx import project_data
from goldens.test_logic_12_4 import group_events, reading

SUFFIX, TWIN = "-13-0", "-12-4"


def pairs() -> list[tuple[str, str]]:
    """(13.0 key, the original session) over the owner's sessions — the owner manifest's keys alone: the public
    corpus names this tool's 13.0 writes `<family>-ours-13-0` too."""
    public = set(json.loads(_goldens.PUBLIC.read_text()))
    known = {k for k, e in _goldens.manifest().items() if isinstance(e, dict) and "path" in e} - public
    return sorted((k, k[:-len(SUFFIX)]) for k in known
                  if k.endswith(SUFFIX) and not k.endswith("-logic" + SUFFIX) and k[:-len(SUFFIX)] in known)


class Logic130OwnerResavesTest(unittest.TestCase):
    def found(self) -> list[tuple[str, str]]:
        out = [(k, t) for k, t in pairs() if _goldens.path(k) is not None and _goldens.path(t) is not None]
        if not out:
            self.skipTest("the owner's 13.0 twins are not on this machine")
        return out

    def test_the_sessions_are_staged(self):
        found = self.found()
        self.assertEqual([k for k, t in pairs() if (k, t) not in found], [])
        self.assertEqual(len(found), _goldens.fact("owner-13-0-twins", "count"))     # the owner manifest's own count

    def test_each_re_save_reads_as_the_original_but_for_rows_listed_twice(self):
        dropped = 0
        for key, original in self.found():
            with self.subTest(key):
                data = project_data(_goldens.path(key))
                self.assertEqual(file_format(data), 2514)
                mine, was = reading(key), reading(original)
                self.assertEqual({k: v for k, v in mine.items() if k not in ("rows", "stacks")},
                                 {k: v for k, v in was.items() if k not in ("rows", "stacks")})
                twice = Counter(was["rows"]) - Counter(mine["rows"])
                self.assertEqual(set(twice), {r for r, n in Counter(was["rows"]).items() if n > 1})
                self.assertEqual(Counter(mine["rows"]), Counter(was["rows"]) - twice)
                self.assertEqual(project_metadata(_goldens.path(original)).get("tracks") - project_metadata(_goldens.path(key)).get("tracks"), sum(twice.values()))
                if not twice:
                    self.assertEqual(mine["stacks"], was["stacks"])
                self.assertEqual(sum(twice.values()), _goldens.fact(key, "rows_written_once"))     # the owner manifest's count
                dropped += sum(twice.values())
                self.assertEqual(validate_project(data), [])
        self.assertEqual(dropped, _goldens.fact("owner-13-0-twins", "rows_written_once"))

    def test_a_groups_events_are_the_originals_where_12_4_dropped_volume(self):
        seen = 0
        for key, original in self.found():
            mine, was = group_events(key), group_events(original)
            if not was:
                continue
            seen += 1
            with self.subTest(key):
                self.assertEqual(mine, was)
                self.assertEqual(group_errors(project_data(_goldens.path(key))), [])
                twin = original + TWIN
                if _goldens.path(twin) is not None:
                    gone = {n: events - group_events(twin)[n] for n, events in was.items()}
                    self.assertTrue(any(gone.values()))
                    self.assertEqual({f for events in gone.values() for _m, f in events}, {FADER_IDS["Volume"]})
        if not seen:
            self.skipTest("no session with a group is on this machine")


if __name__ == "__main__":
    unittest.main()
