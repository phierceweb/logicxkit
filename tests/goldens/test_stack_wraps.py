"""A stack moved into a summing stack, a track moved into a folder inside one, and a stack made
around a stack, each held to Logic 12.4's own drag or Create Track Stack and to Logic's re-save
of the written copy; a third level of stack and the convert of a folder that holds a stack are
refused, as Logic's menu and its own convert show why. Row order aside for the moves: a drag
drops where the pointer is, a write appends. Skips without the public corpus."""

import unittest

import _goldens

from logicxkit.logic.services.arrange.environment import channel_objects
from logicxkit.logic.services.arrange.stack_convert import convert_to_summing
from logicxkit.logic.services.arrange.stack_create import create_stack
from logicxkit.logic.services.arrange.stack_moves import move_to_stack
from logicxkit.logic.services.arrange.stack_summing import create_summing_stack
from logicxkit.logic.services.arrange.stacks import read_stacks, read_tracks
from logicxkit.logic.services.mixer.binding import channels, input_labels, output_labels
from logicxkit.logic.services.mixer.mixer import is_mixer_record
from logicxkit.logic.services.project.project import project_metadata
from logicxkit.logic.services.stream.integrity import regressions
from logicxkit.logic.services.stream.stream import HEADER, project_records
from logicxkit.logic.services.stream.validate import validate_project
from logicxkit.logicx import project_data

# (the saves' stem, the row moved, the stack it went into)
MOVED = (("stack-drag-into-folder", "Audio 3", "F"),
         ("stack-folder-into-summing", "F", "S"),
         ("stack-summing-into-summing", "T", "S"))
AROUND_SUMMING, AROUND_FOLDER = "stack-folder-around-summing", "stack-summing-around-folder"
AROUND_BOTH = "stack-summing-around-summing-after-logic"        # on AROUND_SUMMING's before
HOLDING = "stack-convert-holding-folder"
KEYS = [f"{stem}-{side}-logic" for stem in [m[0] for m in MOVED] + [AROUND_SUMMING, AROUND_FOLDER]
        for side in ("before", "after")] + [AROUND_BOTH]
WRITTEN = [m[0] for m in MOVED] + [AROUND_SUMMING, AROUND_FOLDER, "stack-summing-around-summing",
                                   "stack-convert-mutelane", "stack-convert-muted"]


def load(key: str) -> tuple[bytes, int]:
    bundle = _goldens.path(key)
    return project_data(bundle), project_metadata(bundle)["tracks"]


def obj(data: bytes, name: str) -> int:
    return next(i for i, o in channel_objects(data).items() if o.name == name)


def routing(data: bytes) -> dict[str, tuple]:
    ins, outs = input_labels(data), output_labels(data)
    return {c.label: (ins.get(o), outs.get(o)) for o, c in channels(data).items() if c.in_use}


def channel_records(data: bytes, like: bytes | None = None) -> dict[int, bytes]:
    """owner -> channel record; with ``like``, each channel's own UUID told as ``like``'s."""
    found = {r.owner: r.raw[HEADER:] for r in project_records(data) if is_mixer_record(r)}
    if like is not None:
        mine, theirs = channels(data), channels(like)
        told = {mine[o].uuid: theirs[o].uuid for o in mine if o in theirs and mine[o].uuid != theirs[o].uuid}
        for owner, raw in found.items():
            for uuid, as_logic in told.items():
                raw = raw.replace(uuid, as_logic)
            found[owner] = raw
    return found


def placed(data: bytes, count: int, order: bool = True) -> dict:
    """Rows with their depth, each stack's members, every channel's routing and stack index."""
    rows = [(r["name"], r["depth"]) for r in read_tracks(data, count)]
    stacks = {s.name: (s.kind, s.strip, [n for _k, n in s.members]) for s in read_stacks(data, count)}
    if not order:
        rows, stacks = sorted(rows), {name: (kind, strip, sorted(members)) for name, (kind, strip, members) in stacks.items()}
    return {"rows": rows, "stacks": stacks, "routing": routing(data),
            "stack index": {c.label: c.stack_index for c in channels(data).values() if c.in_use}}


def parents(data: bytes) -> dict[str, str]:
    objects = channel_objects(data)
    return {o.name: objects[o.parent].name for o in objects.values() if o.parent in objects}


@_goldens.needs(*KEYS)
class StackWrapsTest(unittest.TestCase):
    def test_each_save_reads_as_its_facts_say(self):
        for key in KEYS:
            with self.subTest(key):
                data, count = load(key)
                got = placed(data, count)
                self.assertEqual(count, _goldens.fact(key, "tracks"))
                self.assertEqual([[n, d] for n, d in got["rows"] if n != "Stereo Out"], _goldens.fact(key, "rows"))
                self.assertEqual({k: list(v) for k, v in got["stacks"].items()}, _goldens.fact(key, "stacks"))
                outs = {label: out for label, (_i, out) in got["routing"].items()}
                self.assertEqual({k: outs[k] for k in _goldens.fact(key, "outputs")}, _goldens.fact(key, "outputs"))
                self.assertEqual(parents(data), _goldens.fact(key, "parents"))

    def test_a_move_changes_what_logics_drag_changed(self):
        for stem, row, into in MOVED:
            with self.subTest(stem):
                data, count = load(f"{stem}-before-logic")
                logic, logic_count = load(f"{stem}-after-logic")
                out = move_to_stack(data, obj(data, row), obj(data, into), count)
                self.assertEqual(placed(out, count, order=False), placed(logic, logic_count, order=False))
                self.assertEqual(channel_records(out), channel_records(logic))
                self.assertEqual((validate_project(out), regressions(data, out)), ([], []))

    def test_a_track_into_a_folder_inside_a_summing_stack_keeps_its_output(self):
        data, count = load("stack-drag-into-folder-before-logic")
        out = move_to_stack(data, obj(data, "Audio 3"), obj(data, "F"), count)
        self.assertEqual((routing(out)["Audio 3"][1], routing(out)["Audio 1"][1]), ("Output 1-2", "Bus 1"))

    def test_a_summing_stack_moved_in_sends_its_aux_to_the_outer_bus_and_leaves_its_members(self):
        data, count = load("stack-summing-into-summing-before-logic")
        out = move_to_stack(data, obj(data, "T"), obj(data, "S"), count)
        self.assertEqual((routing(out)["Aux 2"], routing(out)["Audio 3"][1]), (("Bus 2", "Bus 1"), "Bus 2"))

    def test_a_folder_around_a_summing_stack_reads_as_logics_own(self):
        data, count = load(f"{AROUND_SUMMING}-before-logic")
        logic, logic_count = load(f"{AROUND_SUMMING}-after-logic")
        out, report = create_stack(data, name="Sub 2", members=[obj(data, "Sum 1")], track_count=count)
        self.assertEqual((report["label"], placed(out, count + 1)), ("Sub 2", placed(logic, logic_count)))
        self.assertEqual((validate_project(out), regressions(data, out)), ([], []))

    def test_a_summing_stack_around_a_folder_reads_as_logics_own(self):
        data, count = load(f"{AROUND_FOLDER}-before-logic")
        logic, logic_count = load(f"{AROUND_FOLDER}-after-logic")
        out, report = create_summing_stack(data, name="Sum 1", members=[obj(data, "Sub 1")], track_count=count)
        self.assertEqual((report["bus"], report["output"], report["left"]), ("Bus 1", "Output 1-2", {}))
        self.assertEqual(placed(out, count + 1), placed(logic, logic_count))
        self.assertEqual(parents(out), parents(logic))
        was, mine, theirs = channel_records(data), channel_records(out, like=logic), channel_records(logic)
        written = {o for o, raw in channel_records(out).items() if raw != was.get(o)}
        self.assertEqual({channels(out)[o].label for o in written}, {"Audio 1", "Audio 2", "Audio 3", "Aux 1", "Bus 1"})
        self.assertEqual({o: mine[o] for o in written}, {o: theirs[o] for o in written})
        self.assertEqual((validate_project(out), regressions(data, out)), ([], []))

    def test_a_summing_stack_around_a_summing_stack_reads_as_logics_own(self):
        data, count = load(f"{AROUND_SUMMING}-before-logic")
        logic, logic_count = load(AROUND_BOTH)
        out, report = create_summing_stack(data, name="Sum 2", members=[obj(data, "Sum 1")], track_count=count)
        self.assertEqual((report["bus"], report["output"]), ("Bus 2", "Output 1-2"))
        self.assertEqual(placed(out, count + 1), placed(logic, logic_count))
        self.assertEqual(parents(out), parents(logic))
        was, mine, theirs = channel_records(data), channel_records(out, like=logic), channel_records(logic)
        written = {o for o, raw in channel_records(out).items() if raw != was.get(o)}
        self.assertEqual({channels(out)[o].label for o in written}, {"Aux 1", "Aux 2", "Bus 2"})
        self.assertEqual({o: mine[o] for o in written}, {o: theirs[o] for o in written})
        self.assertEqual((validate_project(out), regressions(data, out)), ([], []))

    def test_a_third_level_is_refused_where_logic_disables_create_track_stack(self):
        data, count = load(f"{AROUND_SUMMING}-after-logic")              # Sub 2 { Sum 1 { three tracks } }
        for names in (("Sub 2",), ("Sum 1",), ("Audio 1", "Audio 2")):
            for make in (create_stack, create_summing_stack):
                with self.subTest(names, make=make.__name__), self.assertRaisesRegex(ValueError, "two deep"):
                    make(data, name="Third", members=[obj(data, n) for n in names], track_count=count)
        two, two_count = load("stack-summing-into-summing-after-logic")  # S { Audio 1, T { Audio 3 }, Audio 2 }
        wrapped, _r = create_stack(two, name="F", members=[obj(two, "Audio 1")], track_count=two_count)
        with self.assertRaisesRegex(ValueError, "two deep"):
            move_to_stack(wrapped, obj(wrapped, "T"), obj(wrapped, "F"), two_count + 1)


@_goldens.needs(f"{HOLDING}-before-logic", f"{HOLDING}-after-logic")
class FolderHoldingAStackTest(unittest.TestCase):
    def test_logics_own_convert_leaves_no_stack_and_a_row_bound_to_nothing(self):
        data, count = load(f"{HOLDING}-after-logic")
        rows = read_tracks(data, count)
        self.assertEqual((count, read_stacks(data, count)), (_goldens.fact(f"{HOLDING}-after-logic", "tracks"), []))
        self.assertEqual([r["depth"] for r in rows if r["name"] != "Stereo Out"], _goldens.fact(f"{HOLDING}-after-logic", "depths"))
        self.assertNotIn(rows[0]["object_id"], channel_objects(data))

    def test_such_a_folder_is_not_converted(self):
        data, count = load(f"{HOLDING}-before-logic")
        with self.assertRaisesRegex(ValueError, "it holds the stack 'Sub 1'"):
            convert_to_summing(data, obj(data, "Sub 2"), count)


@_goldens.needs(*(f"{stem}-{side}" for stem in WRITTEN for side in ("ours", "resave-logic")))
class LogicKeptTheWrittenCopiesTest(unittest.TestCase):
    def test_each_copy_came_back_with_every_row_route_parent_and_channel_record(self):
        for stem in WRITTEN:
            with self.subTest(stem):
                ours, count = load(f"{stem}-ours")
                logic, logic_count = load(f"{stem}-resave-logic")
                self.assertEqual(placed(ours, count), placed(logic, logic_count))
                self.assertEqual(parents(ours), parents(logic))
                mine, theirs = channel_records(ours), channel_records(logic)
                moved = {channels(logic)[o].label for o in mine if mine[o] != theirs.get(o)}
                self.assertLessEqual(moved, {"Inst 1", "Aux 1"} if stem == "stack-convert-mutelane" else {"Inst 1"})
                self.assertEqual(validate_project(logic), [])
                for fact in ("rows", "stacks", "outputs", "lanes"):
                    self.assertEqual(_goldens.fact(f"{stem}-ours", fact), _goldens.fact(f"{stem}-resave-logic", fact))


if __name__ == "__main__":
    unittest.main()
