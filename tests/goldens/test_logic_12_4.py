"""Logic 12.4's re-saves of the written public bundles, staged beside Logic 12.3.1's as
`<key>-12-4`: each has its twin's record list, tag for tag, and reads as its twin does through
every reader below. Skips without the public corpus."""

import unittest

import _goldens

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
from logicxkit.logic.services.stream.stream import project_records
from logicxkit.logic.services.stream.validate import validate_project
from logicxkit.logicx import project_data

SUFFIX = "-12-4"
# 12.4 keeps an un-named instrument track's object name where 12.3.1 wrote its preset's (manifest note)
RENAMED = {"midi-write-resave-logic-12-4": ("Untitled", "Inst 1")}


def pairs() -> list[tuple[str, str]]:
    """(12.4 key, its 12.3.1 twin) over the public manifest, the twin absent when the public
    corpus never held one."""
    public = {k for k, e in _goldens.manifest().items() if isinstance(e, dict) and "path" in e}
    return sorted((k, k[:-len(SUFFIX)]) for k in public if k.endswith(SUFFIX))


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
