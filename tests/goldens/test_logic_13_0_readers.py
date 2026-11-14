"""Every reader on Logic 13.0's re-saves of public 12.4 saves, against its answer on the 12.4 save:
channels, environment objects, track rows, stacks, slot chains, sends, automation, regions, groups,
tempo, markers, sections and strip references read the same project back. The pairs are the 12.4 save and its 13.0 twin, opened and saved with no change."""

import unittest

import _goldens

from logicxkit.logic.services.arrange.environment import channel_objects
from logicxkit.logic.services.arrange.groups import read_groups
from logicxkit.logic.services.arrange.stacks import read_stacks, read_tracks
from logicxkit.logic.services.mixer.binding import channels, input_labels, output_labels
from logicxkit.logic.services.mixer.chains import channel_references
from logicxkit.logic.services.mixer.plugins import slot_payloads
from logicxkit.logic.services.mixer.sends import read_sends
from logicxkit.logic.services.regions.audio_regions import read_audio_regions
from logicxkit.logic.services.regions.automation import read_automation
from logicxkit.logic.services.song.arrangement import read_sections
from logicxkit.logic.services.song.markers import read_markers
from logicxkit.logic.services.song.metronome import read_metronome
from logicxkit.logic.services.song.tempo import read_tempo_events
from logicxkit.logic.services.stream.validate import file_format
from logicxkit.logicx import project_data

PAIRS = (("tracks-two-audio-logic", "tracks-two-audio-13-0-logic"),
         ("stack-summing-logic", "stack-summing-13-0-logic"),
         ("inserts-native-all-logic", "inserts-native-all-13-0-logic"),
         ("send-two-base-3-logic", "send-two-base-3-13-0-logic"),
         ("automation-volume-fade-logic", "automation-volume-fade-13-0-logic"),
         ("tracks-instrument-logic", "tracks-instrument-13-0-logic"),
         ("stack-folder-logic", "stack-folder-13-0-logic"),
         ("regions-a10-midi-split-logic", "regions-a10-midi-split-13-0-logic"),
         ("group-drums-logic", "group-drums-13-0-logic"),
         ("tempo-point-140-logic", "tempo-point-140-13-0-logic"),
         ("markers-a23-second-logic", "markers-a23-second-13-0-logic"),
         ("strip-reference-chains-resave-logic", "strip-reference-chains-resave-13-0-logic"))


def picture(data: bytes, count: int | None) -> dict:
    chans = channels(data)
    return {"channels": sorted(((c.label, c.in_use) for c in chans.values()), key=repr),
            "objects": sorted((o.name for o in channel_objects(data).values() if o.name), key=repr),
            "rows": [(t["name"], t["label"], t["member"]) for t in read_tracks(data, count)],
            "stacks": [(s.name, s.kind, [n for _k, n in s.members]) for s in read_stacks(data, count)],
            "slots": sorted(((r.channel, r.name) for r, _p in slot_payloads(data)), key=repr),
            "sends": sorted(((chans[o].label, x.bus) for o, sends in read_sends(data).items() for x in sends if o in chans), key=repr),
            "routing": sorted(((c.label, output_labels(data).get(o), input_labels(data).get(o)) for o, c in chans.items() if c.in_use), key=repr),
            "automation": sorted(((a.track, len(a.lanes)) for a in read_automation(data, count)), key=repr),
            "regions": [(r.name, r.start, r.frames, r.piece) for r in read_audio_regions(data, count)],
            "groups": [(g.number, g.name, g.flags, len(g.members)) for g in read_groups(data)],
            "tempo": [(e.position, e.bpm, e.generated) for e in read_tempo_events(data)],
            "markers": [(k.name, k.tick, k.length) for k in read_markers(data)],
            "sections": [(k.name, k.start, k.length, k.kind) for k in read_sections(data)],
            "references": sorted((chans[o].label, ref) for o, ref in channel_references(data).items() if o in chans),
            "metronome": read_metronome(data)}


@_goldens.needs(*(k for pair in PAIRS for k in pair))
class ReadersUnder13Test(unittest.TestCase):
    def test_every_reader_gives_the_12_4_answer_on_the_13_0_twin(self):
        for base, twin in PAIRS:
            with self.subTest(twin=twin):
                old, new = project_data(_goldens.path(base)), project_data(_goldens.path(twin))
                self.assertEqual((file_format(old), file_format(new)), (2513, 2514))
                count = _goldens.manifest()[twin].get("facts", {}).get("tracks")
                self.assertEqual(picture(new, count), picture(old, count))


if __name__ == "__main__":
    unittest.main()
