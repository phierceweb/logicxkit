"""Logic 12.4's re-saves, staged beside Logic 12.3.1's as `<key>-12-4` — the written public
bundles, the stock plug-in saves and, on the owner's machine, each session: each has its twin's
record list, tag for tag, and reads as its twin does through every reader below. The one
difference is on sessions with groups: each group keeps its settings and members and loses its
members' Volume events. Skips without the public corpus."""

import struct
import unittest

import _goldens

from logicxkit.logic.services.arrange.groups import (
    EVENT, EVENT_FADER_AT, EVENT_OBJECT_AT, FADER_IDS, TAIL, group_errors, read_groups,
)
from logicxkit.logic.services.arrange.stacks import read_stacks, read_tracks
from logicxkit.logic.services.midi.midi import read_midi
from logicxkit.logic.services.mixer.binding import channels, input_labels, output_labels
from logicxkit.logic.services.mixer.levels import read_levels
from logicxkit.logic.services.mixer.plugins import slot_payloads
from logicxkit.logic.services.project.project import project_metadata
from logicxkit.logic.services.regions.audio_regions import read_audio_regions
from logicxkit.logic.services.regions.automation import read_automation
from logicxkit.logic.services.song.markers import read_markers
from logicxkit.logic.services.song.signature import read_signatures
from logicxkit.logic.services.song.tempo import read_tempo_events
from logicxkit.logic.services.stream.stream import HEADER, project_records
from logicxkit.logic.services.stream.validate import validate_project
from logicxkit.logicx import project_data

SUFFIX = "-12-4"
# 12.4 keeps an un-named instrument track's object name where 12.3.1 wrote its preset's (manifest note)
RENAMED = {"midi-write-resave-logic-12-4": ("Untitled", "Inst 1")}


VIEW_AT, VIEW_BIT = 151, 0x10     # set in a slot's payload while its window has been open
# the plug-ins whose state 12.4's save of an unopened project changed past it (the logic README)
RESTATED = {"Pedalboard", "ChromaVerb", "Tuner", "Space Designer", "Remix FX", "Beat Breaker", "iZtp/ZAZH"}


def pairs() -> list[tuple[str, str]]:
    """(12.4 key, its 12.3.1 twin) over both manifests, the twin absent when the corpus never
    held one."""
    known = {k for k, e in _goldens.manifest().items() if isinstance(e, dict) and "path" in e}
    return sorted((k, k[:-len(SUFFIX)]) for k in known if k.endswith(SUFFIX))


def group_events(key: str) -> dict[int, set[tuple[int, int]]]:
    """group number -> the (member object, fader id) of each event its `qSvE` holds."""
    data = project_data(_goldens.path(key))
    records = project_records(data)
    out = {}
    for g in read_groups(data):
        events = records[g.start + 2].raw[HEADER:]
        out[g.number] = {(struct.unpack_from("<I", events, k + EVENT_OBJECT_AT)[0] // 2, events[k + EVENT_FADER_AT])
                         for k in range(0, len(events) - TAIL, EVENT)}
    return out


def reading(key: str, rename: tuple[str, str] | None = None) -> dict:
    """What the readers make of the bundle: rows, stacks, routing and levels, plug-ins, regions,
    lanes, markers, tempo and meter."""
    bundle = _goldens.path(key)
    data, count = project_data(bundle), project_metadata(bundle).get("tracks")
    chans, outs, ins, levels = channels(data), output_labels(data), input_labels(data), read_levels(data)
    named = dict([rename]) if rename else {}
    return {
        "rows": [(named.get(r["name"], r["name"]), r["label"], r["depth"], r["hidden"]) for r in read_tracks(data, count)],
        "stacks": [(s.name, s.kind, s.strip, [n for _k, n in s.members]) for s in read_stacks(data, count)],
        "strips": sorted((c.label, outs.get(o), ins.get(o), levels.get(o, {}).get("fader_fixed"), levels.get(o, {}).get("pan"))
                         for o, c in chans.items() if c.in_use),
        "plugins": sorted((r.channel, r.key, r.name) for r, _p in slot_payloads(data)),
        "audio": [(r.track, r.name, r.start, r.frames, r.offset, r.muted, r.loop) for r in read_audio_regions(data, count)],
        "midi": [(named.get(r.track, r.track), r.name, r.start, r.loop, len(r.events)) for r in read_midi(data, count)],
        "lanes": sorted((named.get(a.track, a.track) or "", ln.parameter, tuple((p.tick, p.value) for p in ln.points))
                        for a in read_automation(data, count) for ln in a.lanes),
        "markers": [(m.name, m.tick, m.length) for m in read_markers(data)],
        "tempo": [(e.position, e.bpm, e.generated) for e in read_tempo_events(data)],
        "meter": repr(read_signatures(data)),
        "groups": [(g.number, g.name, g.flags, g.members) for g in read_groups(data)],
    }


class Logic124ResavesTest(unittest.TestCase):
    def test_the_re_saves_are_staged(self):
        self.assertGreaterEqual(len(pairs()), 61)

    def test_each_re_save_reads_as_its_twin(self):
        for key, twin in pairs():
            if _goldens.path(key) is None or _goldens.path(twin) is None:
                continue
            with self.subTest(key):
                ours, theirs = project_data(_goldens.path(key)), project_data(_goldens.path(twin))
                self.assertEqual([r.tag for r in project_records(ours)], [r.tag for r in project_records(theirs)])
                self.assertEqual(reading(key), reading(twin, RENAMED.get(key)))
                self.assertEqual(validate_project(ours), [])

    def test_a_groups_events_are_its_twins_or_those_less_the_volume_ones(self):
        seen = 0
        for key, twin in pairs():
            if _goldens.path(key) is None or _goldens.path(twin) is None:
                continue
            mine, was = group_events(key), group_events(twin)
            if not was:
                continue
            seen += 1
            with self.subTest(key):
                self.assertEqual(sorted(mine), sorted(was))
                for number, events in was.items():
                    gone = events - mine[number]
                    self.assertLessEqual(mine[number], events)
                    self.assertEqual({fader for _m, fader in gone} - {FADER_IDS["Volume"]}, set())
                self.assertEqual(group_errors(project_data(_goldens.path(key))), [])
        if not seen:
            self.skipTest("no save with a group has a twin on this machine")

    def test_the_stock_plug_ins_keep_their_layout_and_all_but_a_few_their_state(self):
        """The parameter tables were measured on 12.3.1's saves (`stockfx-*`). 12.4 saves every
        slot at the same length; bit 0x10 of `+151` is cleared on slots whose window the 12.3.1
        session had open; past that byte only the plug-ins in `RESTATED` differ."""
        found = [(key, twin) for key, twin in pairs() if key.startswith("stockfx-") and _goldens.path(key) is not None]
        if not found:
            self.skipTest("no public corpus")
        self.assertEqual(len(found), 32)
        restated = set()
        for key, twin in found:
            with self.subTest(key):
                mine, was = (slot_payloads(project_data(_goldens.path(k))) for k in (key, twin))
                self.assertEqual([(r.channel, r.key, r.name, len(p)) for r, p in mine],
                                 [(r.channel, r.key, r.name, len(p)) for r, p in was])
                for (ref, new), (_ref, old) in zip(mine, was, strict=True):
                    at = [i for i in range(len(new)) if new[i] != old[i]]
                    self.assertIn(old[VIEW_AT] - new[VIEW_AT], (0, VIEW_BIT), ref.name)
                    if set(at) - {VIEW_AT}:
                        restated.add(ref.name)
        self.assertEqual(restated, RESTATED)

    def test_the_one_rename_is_still_there(self):
        """The allowance above is the whole difference, not a mask over a wider one."""
        key = next(iter(RENAMED))
        if _goldens.path(key) is None:
            self.skipTest("no public corpus")
        old, new = RENAMED[key]
        self.assertIn(new, [r[0] for r in reading(key)["rows"]])
        self.assertIn(old, [r[0] for r in reading(key[:-len(SUFFIX)])["rows"]])


if __name__ == "__main__":
    unittest.main()
