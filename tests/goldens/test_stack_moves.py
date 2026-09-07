"""Rows moving out of, into and between stacks, and an aux track add — each pinned to a
Logic save of that one move (2026-09-04)."""

import struct
import unittest

import _paths  # noqa: F401
from logicxkit.logic.services.binding import bound_channels, channels
from logicxkit.logic.services.environment import channel_objects, object_record
from logicxkit.logic.services.insert import HEADER, project_records
from logicxkit.logic.services.stacks import move_out_of_stack, move_to_stack, read_stacks, read_tracks
from _data import needs

E = _paths.RESOURCES / "experiments"
COUNT = 56


def _have(*names):
    return all((E / f"{n}.logicx").exists() for n in names)


def _load(name):
    from logicxkit.logicx import project_data
    return project_data(E / f"{name}.logicx")


def _shape(data, count=COUNT):
    """What a drag changes: row order, membership, parents and stack indices."""
    rows = read_tracks(data, count)
    objs = channel_objects(data)
    owners = bound_channels(data)
    chans = channels(data)
    return [(r["name"], r["member"], objs[r["object_id"]].parent if r["object_id"] in objs else None,
             chans[owners[r["object_id"]]].stack_index if r["object_id"] in owners else None) for r in rows]


@unittest.skipIf(not _have("13-header-baseline", "30-move-out-of-stack", "31-move-into-stack",
                           "32-move-between-stacks", "33-new-track-next-channel", "34-move-into-stack"),
                 "the stack-move saves are not present")
class GoldenStackMoveTest(unittest.TestCase):
    def object(self, data, name):
        return next(oid for oid, o in channel_objects(data).items() if o.name == name)

    def holding(self, data, member):
        """The stack a track sits in, by name — the saves' own names are not ours to assume."""
        return next(s.name for s in read_stacks(data, COUNT)
                    if member in [n for _k, n in s.members])

    def test_out_of_a_stack_matches_logics_drag(self):
        base, logic = _load("13-header-baseline"), _load("30-move-out-of-stack")
        ours = move_out_of_stack(base, self.object(base, "Vox Back"), track_count=COUNT)
        # Logic dropped it at the bottom; the writer puts it right after the stack. Compare
        # everything but the position.
        self.assertEqual(sorted(_shape(ours)), sorted(_shape(logic)))
        parent = self.holding(base, "Vox Back")
        stacks = {s.name: [n for _k, n in s.members] for s in read_stacks(ours, COUNT)}
        self.assertEqual(stacks[parent], ["Vox Main"])
        rows = read_tracks(ours, COUNT)
        i = next(k for k, r in enumerate(rows) if r["name"] == "Vox Back")
        self.assertEqual((rows[i - 1]["name"], rows[i]["member"]), ("Vox Main", False))

    def test_into_a_stack_matches_logics_drag(self):
        base, logic = _load("33-new-track-next-channel"), _load("34-move-into-stack")
        ours = move_to_stack(base, self.object(base, "Gtr Clean"), self.object(base, "Vox EFX"), track_count=COUNT)
        self.assertEqual(sorted(_shape(ours)), sorted(_shape(logic)))
        self.assertEqual([n for _k, n in next(s for s in read_stacks(ours, COUNT) if s.name == "Vox EFX").members][-1], "Gtr Clean")

    def test_between_stacks_matches_logics_drag(self):
        base, logic = _load("31-move-into-stack"), _load("32-move-between-stacks")
        ours = move_to_stack(base, self.object(base, "Vox Main"), self.object(base, "Vox EFX"), track_count=COUNT)
        self.assertEqual(sorted(_shape(ours)), sorted(_shape(logic)))
        parent = self.holding(base, "Vox Main")
        stacks = {s.name: [n for _k, n in s.members] for s in read_stacks(ours, COUNT)}
        self.assertEqual((stacks[parent], "Vox Main" in stacks["Vox EFX"]), ([], True))


@unittest.skipIf(not _have("34-move-into-stack", "36-new-aux-track"), "the aux-track saves are not present")
@needs("logic", "aux-track-12.3.1.json")
class GoldenAuxTrackTest(unittest.TestCase):
    def test_the_record_set_and_the_channel_match_logics(self):
        from logicxkit.logic.services.addtrack import add_track
        from logicxkit.logic.services.recdiff import diff_records
        base, logic = _load("34-move-into-stack"), _load("36-new-aux-track")
        anchor = next(oid for oid, o in channel_objects(base).items() if o.name == "Gtr Clean")
        ours, report = add_track(base, name="Aux 19", after=anchor, kind="aux", track_count=COUNT)
        self.assertEqual(report["label"], "Aux 19")
        d = diff_records(logic, ours)
        self.assertEqual((d.added, d.removed), ([], []))
        lo, ou = channels(logic), channels(ours)
        self.assertEqual([(o, c.label) for o, c in ou.items() if c.in_use], [(o, c.label) for o, c in lo.items() if c.in_use])
        new = report["owner"]
        pl = next(r.raw[HEADER:] for r in project_records(logic) if r.tag == b"OCuA" and r.owner == new and len(r.raw) > 200)
        po = next(r.raw[HEADER:] for r in project_records(ours) if r.tag == b"OCuA" and r.owner == new and len(r.raw) > 200)
        self.assertEqual([i for i in range(len(pl) - 48) if pl[i] != po[i]], [])       # only the UUIDs differ
        self.assertEqual(po[-32:-16], pl[-32:-16])                                      # same output
        self.assertEqual(po[-16:], pl[-16:])                                            # same input
        rows = {r["name"]: r for r in read_tracks(ours, COUNT + 1)}
        self.assertEqual((rows["Aux 19"]["member"], rows["Aux 19"]["stack_index"], rows["Aux 19"]["colour"]), (True, 6, 5))
        ob = object_record(project_records(ours), report["object_id"])[HEADER:]
        self.assertEqual(struct.unpack_from("<H", ob, 148)[0], 0x1224)


if __name__ == "__main__":
    unittest.main()
