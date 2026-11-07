"""Convert Folder Stack to Summing Stack on the folders Logic was asked about on 2026-11-04, each
`stacks --convert` against Logic's own save: a Mute lane on the folder goes to the reused aux's
track; the reused aux's own lane is dropped for the folder's; an insert on the folder stays on its
Sub strip, out of use; a send feeding the bus from outside does not stop the reuse; the aux's own
track inside the folder makes a new aux the header, with the aux a member on the new bus."""

import struct
import unittest

import _goldens

from logicxkit.logic.services.arrange.environment import PARENT_AT, object_id_of
from logicxkit.logic.services.arrange.stack_convert import convert_to_summing
from logicxkit.logic.services.arrange.stacks import read_stacks, read_tracks
from logicxkit.logic.services.arrange.tracklist import MEMBER_AT, arrange_run, row_object
from logicxkit.logic.services.mixer.binding import channels, input_labels, output_routing
from logicxkit.logic.services.mixer.levels import read_levels
from logicxkit.logic.services.mixer.plugins import slot_payloads
from logicxkit.logic.services.mixer.sends import read_sends
from logicxkit.logic.services.regions.automation import read_automation
from logicxkit.logic.services.stream.stream import HEADER, project_records
from logicxkit.logicx import project_data

CASES = ("mute-lane", "aux-pan-lane", "folder-insert", "send-feeder", "aux-inside")


def picture(data: bytes) -> dict:
    records = project_records(data)
    parents = {object_id_of(r): struct.unpack_from("<I", r.raw, HEADER + PARENT_AT)[0]
               for r in records if object_id_of(r) is not None and len(r.raw) >= HEADER + PARENT_AT + 4}
    tracks = {t["object_id"]: t for t in read_tracks(data)}
    chans, route, feeds = channels(data), output_routing(data), input_labels(data)

    def label(o):
        return chans[o].label if o in chans else o

    return {
        "rows": [(tracks[row_object(records[i].raw)]["name"], records[i].raw[HEADER + MEMBER_AT],
                  tracks[row_object(records[i].raw)].get("label")) for i in arrange_run(records)],
        "parents": [parents.get(row_object(records[i].raw)) for i in arrange_run(records)],
        "stacks": [(s.name, s.kind, [m[1] for m in s.members]) for s in read_stacks(data)],
        "channels": {c.label: (label(route.get(o)), feeds.get(o), c.stack_index) for o, c in chans.items()
                     if c.in_use and c.label.startswith(("Audio", "Sub", "Aux"))},
        "slots": sorted((r.channel, r.name) for r, _p in slot_payloads(data) if not r.midi),
        "sends": {chans[o].label: sorted((s.bus, s.key) for s in ss) for o, ss in read_sends(data).items() if ss},
        "lanes": sorted((tracks.get(a.track_object, {}).get("name", a.track_object),
                         sorted((ln.parameter, [(p.tick, p.value) for p in ln.points]) for ln in a.lanes))
                        for a in read_automation(data) if a.lanes),
        "levels": sorted((c.label, lv["fader_fixed"], lv["pan"], lv["mute"]) for o, lv in read_levels(data).items()
                         for c in [channels(data)[o]] if c.in_use),
    }


@_goldens.needs(*[f"stack-convert-{c}-{s}" for c in CASES for s in ("before", "after-logic")])
class ConvertMeasuredTest(unittest.TestCase):
    def test_ours_leaves_the_project_as_logics_convert_does(self):
        for case in CASES:
            with self.subTest(case):
                before = project_data(_goldens.path(f"stack-convert-{case}-before"))
                after = project_data(_goldens.path(f"stack-convert-{case}-after-logic"))
                folder = next(s for s in read_stacks(before) if s.name == "Sub 1")
                ours, _report = convert_to_summing(before, folder.object_id)
                want, got = picture(after), picture(ours)
                for part in want:
                    self.assertEqual(got[part], want[part], part)



@_goldens.needs("stack-convert-reuse-before-logic", "stack-convert-reuse-auxlane-before-logic")
class UnmeasuredLanePairsTest(unittest.TestCase):
    """A reused-aux convert is measured with a folder Volume lane over any aux lanes and a folder Mute
    lane over an aux with none; a Solo lane, or a Mute lane over an aux that has lanes, is refused."""

    def _with_lane(self, key: str, fader: int) -> tuple[bytes, int]:
        from logicxkit.logic.services.regions.automation_write import set_lane
        data = project_data(_goldens.path(key))
        folder = next(s.object_id for s in read_stacks(data) if s.kind == "folder")
        return set_lane(data, folder, fader, [(0, 1), (3840, 0)]), folder

    def test_a_solo_lane_on_the_folder_is_refused(self):
        data, folder = self._with_lane("stack-convert-reuse-before-logic", 3)         # Solo
        with self.assertRaisesRegex(ValueError, "Solo lane.*not measured"):
            convert_to_summing(data, folder)

    def test_a_mute_lane_over_an_aux_with_lanes_is_refused(self):
        data, folder = self._with_lane("stack-convert-reuse-auxlane-before-logic", 9)   # Mute
        with self.assertRaisesRegex(ValueError, "Mute lane.*Pan, Volume: Logic's convert of that pair is not measured"):
            convert_to_summing(data, folder)

if __name__ == "__main__":
    unittest.main()
