"""Which strip a new stack takes, against Logic 12.4's own Create Track Stack: a folder stack the
lowest `Sub` out of use, put back at 0 dB and not muted, else a new one after the highest; a
summing stack around a folder a new aux that outputs to Output 1-2, whatever bus the folder's
tracks fed. Logic re-saved a written copy of each as written. Skips without the public corpus."""

import unittest

import _goldens
from _stackview import channel_records, load, obj, view

from logicxkit.logic.services.arrange.environment import channel_objects
from logicxkit.logic.services.arrange.stack_create import create_stack
from logicxkit.logic.services.arrange.stack_summing import create_summing_stack
from logicxkit.logic.services.mixer.binding import channels
from logicxkit.logic.services.mixer.levels import UNITY, read_levels
from logicxkit.logic.services.stream.integrity import regressions
from logicxkit.logic.services.stream.validate import validate_project

# (the saves' stem, the track stacked, the strip Logic's new folder took)
SUBS = (("stack-sub-after-flatten", "Audio 3", "Sub 3"),      # Sub 2 in use, heading nothing
        ("stack-sub-gap", "Audio 4", "Sub 2"),                # Sub 2 out of use between Sub 1 and Sub 3
        ("stack-sub-after-convert", "Audio 3", "Sub 2"))      # Sub 2 out of use above the one folder
# (Logic's save before, Logic's save after): folder `Sub 1`, its three tracks all Bus 1 has
BUS_FOLDERS = (("stack-convert-reuse-before-logic", "stack-summing-busfolder-after-logic"),
               ("stack-convert-reuse-track-before-logic", "stack-summing-busfolder-track-after-logic"))
# Logic's convert left `Sub 1` out of use with the folder's level, or its mute, still on it
LEFT = ("stack-sub-level", "stack-sub-muted")
WRITTEN = ("stack-summing-busfolder",) + tuple(stem for stem, _t, _s in SUBS) + LEFT
KEYS = ([f"{stem}-{side}-logic" for stem in [s for s, _t, _s in SUBS] + list(LEFT) for side in ("before", "after")]
        + [k for pair in BUS_FOLDERS for k in pair])


@_goldens.needs(*KEYS)
class NewStackStripTest(unittest.TestCase):
    def test_a_new_folder_takes_the_sub_strip_logics_own_took(self):
        for stem, track, strip in SUBS:
            with self.subTest(stem):
                data, count = load(f"{stem}-before-logic")
                logic, logic_count = load(f"{stem}-after-logic")
                out, report = create_stack(data, name=strip, members=[obj(data, track)], track_count=count)
                mine, theirs = view(out, count + 1), view(logic, logic_count)
                if stem == "stack-sub-gap":          # Logic's own stack left the added track with no input
                    for seen in (mine, theirs):
                        seen["strips"].pop("Audio 4")
                self.assertEqual((report["label"], mine), (strip, theirs))
                self.assertEqual(len(channel_records(out)), len(channel_records(logic)))
                self.assertEqual((validate_project(out), regressions(data, out)), ([], []))

    def test_a_sub_put_back_in_use_changes_only_its_use_and_its_uuid(self):
        data, count = load("stack-sub-after-convert-before-logic")
        out, report = create_stack(data, name="Sub 2", members=[obj(data, "Audio 3")], track_count=count)
        was, now = channel_records(data)[report["owner"]], channel_records(out)[report["owner"]]
        moved = {i for i in range(len(was)) if was[i] != now[i]}
        self.assertEqual({i for i in moved if i < len(was) - 48}, {24, 25})
        self.assertLessEqual(moved, {24, 25} | set(range(len(was) - 48, len(was) - 32)))

    def test_a_sub_left_with_a_level_or_a_mute_comes_back_at_its_defaults(self):
        for stem in LEFT:
            with self.subTest(stem):
                data, count = load(f"{stem}-before-logic")
                logic, logic_count = load(f"{stem}-after-logic")
                sub = next(o for o, c in channels(data).items() if c.label == "Sub 1")
                before = read_levels(data)[sub]
                self.assertTrue(before["fader"] != UNITY or before["mute"])
                out, report = create_stack(data, name="Sub 1", members=[obj(data, "Audio 3")], track_count=count)
                level = read_levels(out)[sub]
                self.assertEqual((report["label"], level["fader"], level["mute"]), ("Sub 1", UNITY, False))
                self.assertEqual(channel_records(out, like=logic), channel_records(logic))
                # the header takes the gone header's object id, as Logic's does, so that object's
                # parked mixer-order row leaves the list in both saves
                mine, theirs = view(out, count + 1), view(logic, logic_count)
                order = lambda seen: [name for name, _at in sorted(seen["table"], key=lambda e: e[1]) if name]   # noqa: E731
                self.assertEqual((mine["flat"], order(mine)), (theirs["flat"], order(theirs)))
                self.assertEqual({k: mine[k] for k in ("rows", "stacks", "strips")},
                                 {k: theirs[k] for k in ("rows", "stacks", "strips")})
                self.assertEqual((validate_project(out), regressions(data, out)), ([], []))

    def test_a_summing_stack_around_a_folder_takes_no_bus_aux_and_outputs_to_the_main_output(self):
        for before, after in BUS_FOLDERS:
            with self.subTest(after):
                data, count = load(before)
                logic, logic_count = load(after)
                out, report = create_summing_stack(data, name="Sum 2", members=[obj(data, "Sub 1")], track_count=count)
                self.assertEqual((report["reused"], report["label"], report["bus"], report["output"]),
                                 (False, "Aux 2", "Bus 2", "Output 1-2"))
                self.assertEqual(report["left"], {f"Audio {n}": "Bus 1" for n in (1, 2, 3)})
                self.assertEqual(view(out, count + 1), view(logic, logic_count))
                colours = lambda d: {o.name: o.colour for o in channel_objects(d).values()}      # noqa: E731
                self.assertEqual(colours(out), colours(logic))
                was, mine, theirs = channel_records(data), channel_records(out, like=logic), channel_records(logic)
                written = {o for o, raw in channel_records(out).items() if raw != was.get(o)}
                self.assertEqual({o: mine[o] for o in written}, {o: theirs[o] for o in written})
                self.assertEqual((validate_project(out), regressions(data, out)), ([], []))


@_goldens.needs(*(f"{stem}-{side}" for stem in WRITTEN for side in ("ours", "resave-logic")))
class LogicKeptTheWrittenCopiesTest(unittest.TestCase):
    def test_each_copy_came_back_as_written(self):
        for stem in WRITTEN:
            with self.subTest(stem):
                ours, count = load(f"{stem}-ours")
                logic, logic_count = load(f"{stem}-resave-logic")
                self.assertEqual(view(ours, count), view(logic, logic_count))
                self.assertEqual(channel_records(ours), channel_records(logic))
                self.assertEqual(validate_project(logic), [])


if __name__ == "__main__":
    unittest.main()
