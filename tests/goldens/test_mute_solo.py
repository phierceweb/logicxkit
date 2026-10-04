"""A channel's mute and solo as Logic 12.4's own buttons saved them, and what its Convert Folder
Stack to Summing Stack does with a folder's mute and its Mute and Solo lanes. Skips without the
public corpus."""

import unittest

import _goldens
from logicxkit.logic.services.arrange.environment import channel_objects
from logicxkit.logic.services.arrange.stack_convert import convert_to_summing
from logicxkit.logic.services.mixer.binding import channels
from logicxkit.logic.services.mixer.levels import MUTE_AT, SOLO_AT, read_levels
from logicxkit.logic.services.mixer.mixer import is_mixer_record
from logicxkit.logic.services.project.project import project_metadata
from logicxkit.logic.services.regions.automation import read_automation
from logicxkit.logic.services.stream.integrity import regressions
from logicxkit.logic.services.stream.stream import HEADER, project_records
from logicxkit.logicx import project_data

BASE, MUTED, SOLOED = "mute-base-logic", "mute-audio-1-logic", "solo-audio-2-logic"
FOLDER_MUTED, CONVERTED = "stack-folder-muted-logic", "stack-convert-muted-after-logic"
LANES = {"Mute": ("stack-convert-mutelane-before-logic", "stack-convert-mutelane-after-logic"),
         "Solo": ("stack-convert-sololane-before-logic", "stack-convert-sololane-after-logic")}


def load(key: str) -> tuple[bytes, int]:
    bundle = _goldens.path(key)
    return project_data(bundle), project_metadata(bundle)["tracks"]


def state(data: bytes) -> dict[str, list[str]]:
    levels, chans = read_levels(data), channels(data)
    return {"muted": sorted(chans[o].label for o, v in levels.items() if v["mute"]),
            "soloed": sorted(chans[o].label for o, v in levels.items() if v["solo"])}


def lanes(data: bytes, count: int) -> list:
    return [[a.track, ln.parameter, [[p.tick, p.value] for p in ln.points]]
            for a in read_automation(data, count) for ln in a.lanes]


def folder(data: bytes) -> int:
    return next(i for i, o in channel_objects(data).items() if o.name == "Sub 1")


@_goldens.needs(BASE, MUTED, SOLOED, FOLDER_MUTED, CONVERTED)
class MuteSoloTest(unittest.TestCase):
    def test_each_save_reads_the_buttons_logic_had_pressed(self):
        for key in (BASE, MUTED, SOLOED, FOLDER_MUTED, CONVERTED):
            with self.subTest(key):
                got = state(load(key)[0])
                self.assertEqual(got, {k: _goldens.fact(key, k) for k in got})

    def test_a_press_changes_one_bit_of_the_channel(self):
        def bytes_at(key: str, label: str) -> tuple[int, int]:
            data = load(key)[0]
            owner = next(o for o, c in channels(data).items() if c.label == label)
            raw = next(r.raw for r in project_records(data) if is_mixer_record(r) and r.owner == owner)
            return raw[HEADER + MUTE_AT], raw[HEADER + SOLO_AT]
        self.assertEqual((bytes_at(BASE, "Audio 1"), bytes_at(MUTED, "Audio 1")), ((0, 0), (1, 0)))
        self.assertEqual((bytes_at(MUTED, "Audio 2"), bytes_at(SOLOED, "Audio 2")), ((0, 0), (0, 1)))
        self.assertEqual(bytes_at(SOLOED, "Audio 3"), (2, 0))             # silenced by the solo, not muted

    def test_a_muted_folder_converts_with_its_mute_left_on_the_sub(self):
        data, count = load(FOLDER_MUTED)
        out, report = convert_to_summing(data, folder(data), count)
        self.assertEqual((report["mute_left"], state(out)), (True, state(load(CONVERTED)[0])))
        self.assertEqual(regressions(data, out), [])


@_goldens.needs(*(key for pair in LANES.values() for key in pair))
class CarriedLanesTest(unittest.TestCase):
    def test_a_mute_or_solo_lane_moves_onto_the_new_header_as_logics_convert_moved_it(self):
        for parameter, (before, after) in LANES.items():
            with self.subTest(parameter):
                data, count = load(before)
                out, report = convert_to_summing(data, folder(data), count)
                logic, logic_count = load(after)
                self.assertEqual(lanes(out, count + report["tracks_added"]), lanes(logic, logic_count))
                self.assertEqual(lanes(logic, logic_count), _goldens.fact(after, "lanes"))
                self.assertEqual(regressions(data, out), [])


if __name__ == "__main__":
    unittest.main()
