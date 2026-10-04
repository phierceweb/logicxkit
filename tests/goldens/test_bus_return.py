"""A bus put in use as Logic 12.4's own output change leaves one (`route-out-bus-logic`): a UUID
of its own in place of the placeholder, and the lowest free aux in use fed from it, with an
object and a sequence and no track. Skips without the public corpus."""

import unittest
from collections import Counter
from unittest import mock

import _goldens
from logicxkit.logic.services.arrange.bus_return import use_bus
from logicxkit.logic.services.arrange.environment import SELECTED_AT, STAMP_STEP_AT, channel_objects, object_id_of
from logicxkit.logic.services.arrange.stack_summing import create_summing_stack
from logicxkit.logic.services.arrange.stacks import read_stacks, read_tracks
from logicxkit.logic.services.arrange.tracklist import arrange_run, flat_run, row_object
from logicxkit.logic.services.mixer.binding import bound_channels, channels, input_labels, output_labels
from logicxkit.logic.services.mixer.mixer import is_mixer_record
from logicxkit.logic.services.mixer.routing import set_output
from logicxkit.logic.services.project.project import project_metadata
from logicxkit.logic.services.stream.integrity import regressions
from logicxkit.logic.services.stream.sequence import index_table, table_entries
from logicxkit.logic.services.stream.stream import HEADER, project_records
from logicxkit.logic.services.stream.validate import validate_project
from logicxkit.logicx import project_data

BLANK = "tracks-three-audio-logic"
PLACEHOLDER = "stack-summing-placeholder-before-logic"   # Audio 1 and 2 on a Bus 1 still on its placeholder
LOGICS_FIRST, LOGICS = "route-out-bus-logic", "route-out-bus-second-logic"   # Logic's own: Audio 1, then Audio 2 too
REUSED = "stack-summing-reuse-logic"
PLACEHOLDER_HEAD = bytes.fromhex("ee0000000000800080")


def load(key: str) -> tuple[bytes, int]:
    bundle = _goldens.path(key)
    return project_data(bundle), project_metadata(bundle)["tracks"]


def owner(data: bytes, label: str) -> int:
    return next(o for o, c in channels(data).items() if c.label == label)


def routing(data: bytes) -> dict[str, tuple]:
    ins, outs = input_labels(data), output_labels(data)
    return {c.label: (ins.get(o), outs.get(o)) for o, c in channels(data).items() if c.in_use}


def shape(data: bytes, count: int) -> dict:
    """What a bus coming into use changes, ids aside: the channels in use and their routing, the
    buses with a UUID of their own, the objects, both track lists, the index table's objects."""
    records, objects = project_records(data), channel_objects(data)
    run = arrange_run(records, count)
    return {"routing": routing(data),
            "buses": sorted(c.label for c in channels(data).values()
                            if c.label.startswith("Bus ") and not c.uuid.startswith(PLACEHOLDER_HEAD)),
            "objects": sorted((o.name, o.colour) for o in objects.values()),
            "aux object": [(r.raw[HEADER + SELECTED_AT], r.raw[HEADER + STAMP_STEP_AT]) for r in records
                           if object_id_of(r) is not None and objects[object_id_of(r)].name == "Aux 1"],
            "bound": sorted((objects[i].name, channels(data)[o].label) for i, o in bound_channels(data).items() if i in objects),
            "rows": [(r["name"], r["depth"]) for r in read_tracks(data, count)],
            "flat": [objects[row_object(records[i].raw)].name for i in flat_run(records, run) if row_object(records[i].raw) in objects],
            "table": sorted(e[1:3] for e in table_entries(records[index_table(records)].raw[HEADER:])),   # object, index
            "tags": Counter(r.tag for r in records)}


def channel_records(data: bytes, like: bytes | None = None) -> dict[int, bytes]:
    """owner -> channel record; with ``like``, each channel's own UUID told as ``like``'s."""
    found = {r.owner: r.raw[HEADER:] for r in project_records(data) if is_mixer_record(r)}
    if like is not None:
        mine, theirs = channels(data), channels(like)
        told = {mine[o].uuid: theirs[o].uuid for o in mine if o in theirs and mine[o].uuid != theirs[o].uuid}
        for o, raw in found.items():
            for uuid, as_logic in told.items():
                raw = raw.replace(uuid, as_logic)
            found[o] = raw
    return found


@_goldens.needs(BLANK, PLACEHOLDER, LOGICS_FIRST, LOGICS, REUSED)
class BusReturnTest(unittest.TestCase):
    def test_a_placeholder_bus_put_in_use_reads_as_logics_own(self):
        """Bus 1 on its placeholder with two outputs set to it and nothing fed from it: put in
        use, the save is Logic's own with the same two outputs set."""
        data, count = load(PLACEHOLDER)
        logic, logic_count = load(LOGICS)
        out, report = use_bus(data, owner(data, "Bus 1"), track_count=count)
        self.assertEqual((report["aux"], report["minted"], count), ("Aux 1", True, logic_count))
        self.assertEqual(shape(out, count), shape(logic, logic_count))
        was, mine, theirs = channel_records(data), channel_records(out, like=logic), channel_records(logic)
        written = {o for o, raw in channel_records(out).items() if raw != was.get(o)}
        self.assertEqual({channels(out)[o].label for o in written}, {"Audio 1", "Audio 2", "Aux 1", "Bus 1"})
        self.assertEqual({o: mine[o] for o in written}, {o: theirs[o] for o in written})
        self.assertEqual((validate_project(out), regressions(data, out)), ([], []))

    def test_an_output_sent_to_an_unused_bus_reads_as_logics_facts_say(self):
        data, count = load(BLANK)
        out, _report = use_bus(data, owner(data, "Bus 1"), track_count=count)
        out = set_output(out, owner(out, "Audio 1"), owner(out, "Bus 1"))
        logic, _n = load(LOGICS_FIRST)
        self.assertEqual(routing(out), routing(logic))
        outs = {label: went for label, (_i, went) in routing(out).items()}
        self.assertEqual({k: outs[k] for k in _goldens.fact(LOGICS_FIRST, "outputs")}, _goldens.fact(LOGICS_FIRST, "outputs"))
        self.assertEqual(routing(out)["Aux 1"][0], _goldens.fact(LOGICS_FIRST, "aux_input"))
        self.assertEqual((validate_project(out), regressions(data, out)), ([], []))

    def test_a_bus_already_in_use_is_left_alone(self):
        data, count = load(LOGICS)
        out, report = use_bus(data, owner(data, "Bus 1"), track_count=count)
        self.assertEqual((out, report["aux"], report["minted"]), (data, None, False))

    def test_a_summing_stack_over_tracks_we_routed_takes_the_bus_aux_as_logics_does(self):
        data, count = load(BLANK)
        out, _report = use_bus(data, owner(data, "Bus 1"), track_count=count)
        for name in ("Audio 1", "Audio 2"):
            out = set_output(out, owner(out, name), owner(out, "Bus 1"))
        objects = {o.name: i for i, o in channel_objects(out).items()}
        made, report = create_summing_stack(out, name="S", members=[objects["Audio 1"], objects["Audio 2"]], track_count=count)
        logic, logic_count = load(REUSED)
        self.assertEqual((report["reused"], report["label"]), (True, "Aux 1"))
        self.assertEqual([(s.name, s.kind, s.strip, [n for _k, n in s.members]) for s in read_stacks(made, count + 1)],
                         [(s.name, s.kind, s.strip, [n for _k, n in s.members]) for s in read_stacks(logic, logic_count)])
        self.assertEqual(routing(made), routing(logic))

    def test_with_no_aux_stub_free_a_fresh_strip_is_made(self):
        data, count = load(BLANK)
        with mock.patch("logicxkit.logic.services.arrange.addtrack.free_aux_stub", side_effect=ValueError("none free")), \
             mock.patch("logicxkit.logic.services.arrange.bus_return.free_aux_stub", side_effect=ValueError("none free")):
            out, report = use_bus(data, owner(data, "Bus 1"), track_count=count)
        self.assertNotEqual(report["aux"], "Aux 1")
        self.assertEqual(routing(out)[report["aux"]], ("Bus 1", "Output 1-2"))
        self.assertEqual((validate_project(out), regressions(data, out)), ([], []))


if __name__ == "__main__":
    unittest.main()
