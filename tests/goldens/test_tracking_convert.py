"""A folder of a tracking session whose members are all their bus has, converted to a summing
stack: ours against Logic 12.4's own convert of the same session, and Logic's re-save of ours.
The bus's aux track is an ordinary track object there (kind 128), and the mixer-order list
opens with rows of objects that are gone. Skips without the owner's files."""

import unittest

import _goldens
from logicxkit.logic.services.arrange.environment import channel_objects
from logicxkit.logic.services.arrange.stack_convert import convert_to_summing
from logicxkit.logic.services.arrange.stack_summing import create_summing_stack
from logicxkit.logic.services.arrange.stacks import FOLDER, SUMMING, read_stacks, read_tracks
from logicxkit.logic.services.arrange.tracklist import arrange_run, flat_run, row_object
from logicxkit.logic.services.mixer.binding import channels, input_labels, output_labels
from logicxkit.logic.services.mixer.mixer import is_mixer_record
from logicxkit.logic.services.project.project import project_metadata
from logicxkit.logic.services.stream.integrity import regressions
from logicxkit.logic.services.stream.sequence import index_table, table_entries
from logicxkit.logic.services.stream.stream import HEADER, project_records
from logicxkit.logic.services.stream.validate import validate_project
from logicxkit.logicx import project_data

BEFORE, LOGICS, OURS, RESAVE = (f"tracking-convert-{k}" for k in ("before", "after-logic", "ours", "resave-logic"))
MOVES_BETWEEN_SAVES = {81}              # a byte of an instrument channel Logic changes on its own saves


def load(key: str) -> tuple[bytes, int]:
    bundle = _goldens.path(key)
    return project_data(bundle), project_metadata(bundle)["tracks"]


def shape(data: bytes, count: int) -> dict:
    records, objects, chans = project_records(data), channel_objects(data), channels(data)
    ins, outs = input_labels(data), output_labels(data)
    return {"tracks": count,
            "rows": [(r["name"], r["label"], r["depth"]) for r in read_tracks(data, count)],
            "stacks": [(s.name, s.kind, s.strip, s.depth, [n for _k, n in s.members]) for s in read_stacks(data, count)],
            "routing": {c.label: (c.in_use, c.stack_index, ins.get(o), outs.get(o)) for o, c in chans.items()},
            "objects": sorted((o.name, o.colour, o.kind, objects[o.parent].name if o.parent in objects else o.parent)
                              for o in objects.values()),
            "flat": [row_object(records[i].raw) for i in flat_run(records, arrange_run(records, count))],
            "table": sorted(e[1:3] for e in table_entries(records[index_table(records)].raw[HEADER:]))}


def changed_bytes(a: bytes, b: bytes) -> dict[str, set[int]]:
    """Label -> the offsets at which a channel's record differs between two saves."""
    was = {r.owner: r.raw[HEADER:] for r in project_records(a) if is_mixer_record(r)}
    now = {r.owner: r.raw[HEADER:] for r in project_records(b) if is_mixer_record(r)}
    return {channels(b)[o].label: {i for i in range(min(len(now[o]), len(was[o]))) if now[o][i] != was[o][i]}
            for o in now if now[o] != was.get(o)}


@_goldens.needs(BEFORE, LOGICS, OURS, RESAVE)
class TrackingConvertTest(unittest.TestCase):
    def test_our_convert_is_logics_own(self):
        data, count = load(BEFORE)
        logic, logic_count = load(LOGICS)
        folder = next(s for s in read_stacks(data, count) if s.name == _goldens.fact(BEFORE, "folder") and s.kind == FOLDER)
        out, report = convert_to_summing(data, folder.object_id, track_count=count)
        self.assertEqual(shape(out, count + report["tracks_added"]), shape(logic, logic_count))
        self.assertEqual(report["reused"], True)
        for label, offsets in changed_bytes(out, logic).items():
            self.assertLessEqual(offsets, MOVES_BETWEEN_SAVES, label)
        self.assertEqual((validate_project(out), regressions(data, out)), ([], []))

    def test_logics_own_reads_as_its_facts_say(self):
        logic, count = load(LOGICS)
        name, strip, members = _goldens.fact(LOGICS, "stack")
        self.assertIn((name, SUMMING, strip, members),
                      [(s.name, s.kind, s.strip, [n for _k, n in s.members]) for s in read_stacks(logic, count)])
        header = next(o for o in channel_objects(logic).values() if o.name == name)
        self.assertEqual({"kind": header.kind, "colour": header.colour}, _goldens.fact(LOGICS, "header"))
        before, before_count = load(BEFORE)
        folder = next(s for s in read_stacks(before, before_count) if s.name == name and s.kind == FOLDER)
        records = project_records(logic)
        flat = [row_object(records[i].raw) for i in flat_run(records, arrange_run(records, count))]
        self.assertNotIn(folder.object_id, channel_objects(logic))
        self.assertEqual(flat.index(folder.object_id) + 1, _goldens.fact(LOGICS, "gone_row_place"))
        self.assertEqual(count, _goldens.fact(LOGICS, "tracks"))

    def test_logic_kept_ours_as_written(self):
        (ours, count), (logic, logic_count) = load(OURS), load(RESAVE)
        self.assertEqual(shape(ours, count), shape(logic, logic_count))
        self.assertEqual(changed_bytes(ours, logic), {})


SUM_LOGICS, SUM_OURS, SUM_RESAVE = (f"tracking-sum-busfolder-{k}" for k in ("after-logic", "ours", "resave-logic"))


@_goldens.needs(BEFORE, SUM_LOGICS, SUM_OURS, SUM_RESAVE)
class SummingAroundTheFolderTest(unittest.TestCase):
    """Create Track Stack… (Summing) over the same folder's header: no bus's aux is reused. A new
    aux outputs to Output 1-2 and the folder's tracks leave their bus for the new one."""

    def placed(self, data: bytes, count: int) -> dict:
        seen = shape(data, count)
        return {k: seen[k] for k in ("tracks", "rows", "stacks", "routing", "objects")}

    def test_our_stack_is_logics_own_but_for_one_dead_row(self):
        data, count = load(BEFORE)
        logic, logic_count = load(SUM_LOGICS)
        folder = next(s for s in read_stacks(data, count) if s.name == _goldens.fact(BEFORE, "folder") and s.kind == FOLDER)
        name, strip, _members = _goldens.fact(SUM_LOGICS, "stack")
        out, report = create_summing_stack(data, name=name, members=[folder.object_id], track_count=count)
        self.assertEqual((report["label"], report["bus"], report["output"], report["reused"]),
                         (strip, _goldens.fact(SUM_LOGICS, "bus"), _goldens.fact(SUM_LOGICS, "output"), False))
        self.assertEqual(set(report["left"].values()), {_goldens.fact(SUM_LOGICS, "left_bus")})
        self.assertEqual(self.placed(out, count + 1), self.placed(logic, logic_count))
        # Logic's save has one fewer of the rows of gone objects that open the mixer-order list
        mine, theirs = shape(out, count + 1)["flat"], shape(logic, logic_count)["flat"]
        names = lambda d, flat: [channel_objects(d)[o].name for o in flat if o in channel_objects(d)]      # noqa: E731
        self.assertEqual(names(out, mine), names(logic, theirs))
        self.assertEqual(len(mine) - len(theirs), 1)
        self.assertEqual((validate_project(out), regressions(data, out)), ([], []))

    def test_logic_kept_the_written_copy(self):
        ours, count = load(SUM_OURS)
        logic, logic_count = load(SUM_RESAVE)
        self.assertEqual(shape(logic, logic_count), shape(ours, count))
        self.assertLessEqual({i for offsets in changed_bytes(ours, logic).values() for i in offsets}, MOVES_BETWEEN_SAVES)


if __name__ == "__main__":
    unittest.main()
