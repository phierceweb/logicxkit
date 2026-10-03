"""A summing stack written here, held to Logic's own Create Track Stack (Summing) over the same
three tracks: the header an aux fed from a bus, the members one level under it and routed to
that bus. Skips without the public corpus."""

import struct
import unittest

import _goldens

from logicxkit.logic.services.mixer.binding import INPUT_WORD_AT, OUTPUT_WORD_AT, bound_channels, channels, input_labels, output_labels
from logicxkit.logic.services.arrange.environment import PARENT_AT, channel_objects, object_record
from logicxkit.logic.services.stream.integrity import regressions
from logicxkit.logic.services.mixer.mixer import channel_formats
from logicxkit.logic.services.arrange.stack_create import create_stack
from logicxkit.logic.services.arrange.stack_summing import create_summing_stack, free_bus
from logicxkit.logic.services.arrange.stacks import SUMMING, read_stacks, read_tracks
from logicxkit.logic.services.stream.stream import HEADER, project_records
from logicxkit.logic.services.stream.validate import validate_project
from logicxkit.logicx import project_data

BASE, LOGICS, FOLDER = "stack-folder-flattened-logic", "stack-summing-logic", "stack-folder-logic"
MEMBERS = ("Audio 1", "Audio 2", "Audio 3")


def shape(data: bytes) -> dict:
    """What a summing stack is, read back: its rows, its header's strip and each member's routing."""
    stack = next(s for s in read_stacks(data) if s.kind == SUMMING)
    chans, widths, outs, ins = channels(data), channel_formats(data), output_labels(data), input_labels(data)
    owners, records = bound_channels(data), project_records(data)
    rows = read_tracks(data)
    members = [r for r in rows if r["name"] in [n for _k, n in stack.members]]
    return {
        "rows": [(r["name"], r["depth"], r["expanded"], r["grouping"]) for r in rows],
        "header": (chans[stack.owner].in_use, widths[stack.owner], outs[stack.owner], ins[stack.owner] is not None),
        "header_bytes": tuple(chans_bytes(records, stack.owner, at) for at in (85, 119)),
        "members_feed_the_header": [outs[r["owner"]] == ins[stack.owner] for r in members],
        "member_words": [chans[r["owner"]].words[0] == chans[stack.owner].words[1] for r in members],
        "parents": [struct.unpack_from("<I", object_record(records, r["object_id"]), HEADER + PARENT_AT)[0] == stack.object_id
                    for r in members],
        "member_stack_index": [chans[owners[r["object_id"]]].stack_index for r in members],
    }


def chans_bytes(records, owner: int, at: int) -> int:
    raw = max((r.raw for r in records if r.tag == b"OCuA" and r.owner == owner and r.key == 0xFFFF), key=len)
    return raw[HEADER + at]


def flat_labels(data: bytes) -> list[str]:
    from logicxkit.logic.services.arrange.tracklist import arrange_run, flat_run, row_object
    records, chans, owners = project_records(data), channels(data), bound_channels(data)
    return [chans[owners[row_object(records[i].raw)]].label.split()[0]
            for i in flat_run(records, arrange_run(records)) if row_object(records[i].raw) in owners]


@_goldens.needs(BASE, LOGICS, FOLDER)
class SummingStackTest(unittest.TestCase):
    def setUp(self):
        self.base = project_data(_goldens.path(BASE))
        objs = {o.name: i for i, o in channel_objects(self.base).items()}
        self.members = [objs[n] for n in MEMBERS]
        self.ours, self.report = create_summing_stack(self.base, name="Sum 1", members=self.members)

    def test_it_reads_as_logics_own_summing_stack_does(self):
        logics = project_data(_goldens.path(LOGICS))
        self.assertEqual(shape(self.ours), shape(logics))
        self.assertEqual(flat_labels(self.ours), flat_labels(logics))
        self.assertEqual(validate_project(self.ours), [])
        self.assertEqual(regressions(self.base, self.ours), [])

    def test_the_header_binds_the_lowest_free_aux_stub_as_logics_does(self):
        """Logic brought `Aux 1`, the lowest free stub, into use; no channel record was made and
        none moved."""
        logics = project_data(_goldens.path(LOGICS))
        stack = next(s for s in read_stacks(self.ours) if s.kind == SUMMING)
        self.assertEqual(channels(self.ours)[stack.owner].label, "Aux 1")
        self.assertEqual(self.report["label"], "Aux 1")
        def strips(data):
            return [(o, c.label, c.size) for o, c in sorted(channels(data).items())]
        self.assertEqual(strips(self.ours), strips(self.base))
        self.assertEqual(strips(self.ours), strips(logics))

    def test_the_bus_is_the_lowest_nothing_uses(self):
        self.assertEqual(self.report["bus"], "Bus 1")
        again = free_bus(self.ours)
        self.assertEqual(channels(self.ours)[again].label, "Bus 2")

    def test_words_and_uuids_name_the_same_bus(self):
        chans = channels(self.ours)
        header = chans[bound_channels(self.ours)[self.report["object_id"]]]
        by_uuid = {c.uuid: c.label for c in chans.values()}
        self.assertEqual(by_uuid[header.input_uuid], "Bus 1")
        member = chans[bound_channels(self.ours)[self.members[0]]]
        self.assertEqual((by_uuid[member.dest_uuid], member.words[0], header.words), ("Bus 1", 1, (0, 1)))
        self.assertEqual((OUTPUT_WORD_AT, INPUT_WORD_AT), (92, 94))

    def test_a_header_and_no_member_are_refused(self):
        folder = project_data(_goldens.path(FOLDER))
        objs = {o.name: i for i, o in channel_objects(folder).items()}
        with self.assertRaisesRegex(ValueError, "stack header"):
            create_summing_stack(folder, name="Sum", members=[objs["Sub 1"]])
        with self.assertRaisesRegex(ValueError, "at least one member"):
            create_summing_stack(self.base, name="Sum", members=[])


OURS, RESAVE, SOURCE = "stack-summing-stub-ours", "stack-summing-stub-resave-logic", "markers-edits-resave-logic"


def whole(data: bytes) -> dict:
    """Every row and every in-use channel's routing: what a re-save has to keep."""
    chans, outs, ins, widths = channels(data), output_labels(data), input_labels(data), channel_formats(data)
    return {"rows": [(r["name"], r["label"], r["owner"], r["depth"]) for r in read_tracks(data)],
            "routes": {c.label: (outs.get(o), ins.get(o), widths.get(o), c.stack_index, c.words)
                       for o, c in chans.items() if c.in_use},
            "stacks": [[s.name, s.strip, ins[s.owner], [n for _k, n in s.members]] for s in read_stacks(data)]}


@_goldens.needs(OURS, RESAVE, SOURCE)
class LogicResavedTest(unittest.TestCase):
    def setUp(self):
        self.ours, self.logics = (project_data(_goldens.path(k)) for k in (OURS, RESAVE))

    def test_logic_kept_every_row_route_and_stack(self):
        self.assertEqual(whole(self.logics), whole(self.ours))
        self.assertEqual(whole(self.ours)["stacks"], _goldens.fact(OURS, "stacks"))
        self.assertEqual([r[0] for r in whole(self.logics)["rows"]], _goldens.fact(RESAVE, "rows"))
        self.assertEqual((validate_project(self.ours), validate_project(self.logics)), ([], []))

    def test_logic_kept_the_channel_records_and_the_header_objects(self):
        def kept(data):
            records = project_records(data)
            headers = {s.object_id for s in read_stacks(data)}
            return ([r.raw for r in records if r.tag == b"OCuA"],
                    [object_record(records, oid) for oid in sorted(headers)])
        self.assertEqual(kept(self.logics), kept(self.ours))

    def test_the_header_is_logics_own_whatever_aux_the_session_patterns_on(self):
        """A session's aux tracks carry kind 128 as often as 0; the header is a grouping object."""
        from logicxkit.logic.services.arrange.environment import KIND_AT, object_id_of
        data = project_data(_goldens.path(SOURCE))
        objs = {o.name: i for i, o in channel_objects(data).items()}
        data, first = create_summing_stack(data, name="First", members=[objs["Audio 1"]])
        buf, at = bytearray(data), 24
        for r in project_records(data):
            if object_id_of(r) == first["object_id"]:
                buf[at + HEADER + KIND_AT] = 128
            at += len(r.raw)
        data = bytes(buf)
        self.assertEqual(read_stacks(data), [])
        out, second = create_summing_stack(data, name="Second", members=[objs["Audio 2"]])
        (stack,) = read_stacks(out)
        self.assertEqual((stack.name, stack.kind, [n for _k, n in stack.members]), ("Second", SUMMING, ["Audio 2"]))
        self.assertEqual(channel_objects(out)[second["object_id"]].kind, 0)

    def test_the_writer_still_makes_what_logic_opened(self):
        """The same steps on the source: every row, route and stack as the staged bundle holds
        them, the headers on the lowest free `Aux` stubs in turn."""
        data = project_data(_goldens.path(SOURCE))
        for name, strip, _bus, members in _goldens.fact(OURS, "stacks"):
            objs = {o.name: i for i, o in channel_objects(data).items()}
            data, report = create_summing_stack(data, name=name, members=[objs[m] for m in members])
            self.assertEqual(report["label"], strip)
        self.assertEqual(whole(data), whole(self.ours))


TWO, DRAGGED_IN, DRAGGED_OUT = "stack-summing-two-ours", "stack-summing-dragged-in-logic", "stack-summing-dragged-out-logic"


def track(data: bytes, name: str) -> dict:
    """One track's place and routing, as a drag changes them."""
    row = next(r for r in read_tracks(data) if r["name"] == name)
    chan = channels(data)[row["owner"]]
    parent = struct.unpack_from("<I", object_record(project_records(data), row["object_id"]), HEADER + PARENT_AT)[0]
    return {"depth": row["depth"], "output": output_labels(data)[row["owner"]], "word": chan.words[0],
            "parent": parent, "stack_index": chan.stack_index}


@_goldens.needs(TWO, DRAGGED_IN, DRAGGED_OUT, "stack-summing-move-ours", "stack-summing-move-resave-logic")
class MoveIntoSummingTest(unittest.TestCase):
    def setUp(self):
        from logicxkit.logic.services.arrange.stack_moves import move_to_stack
        self.base = project_data(_goldens.path(TWO))
        objs = {o.name: i for i, o in channel_objects(self.base).items()}
        self.objs = objs
        self.moved = move_to_stack(self.base, objs["Audio 3"], objs["Sum A"])

    def test_the_track_is_placed_and_routed_as_logics_own_drag_left_it(self):
        logics = project_data(_goldens.path(DRAGGED_IN))
        self.assertEqual(track(self.moved, "Audio 3"), track(logics, "Audio 3"))
        self.assertEqual(track(logics, "Audio 3"), {k: _goldens.fact(DRAGGED_IN, k)
                                                   for k in ("depth", "output", "word", "parent", "stack_index")})
        (ours,), (theirs,) = read_stacks(self.moved), read_stacks(logics)
        self.assertEqual(sorted(n for _k, n in ours.members), sorted(n for _k, n in theirs.members))
        self.assertEqual([n for _k, n in ours.members], ["Audio 1", "Audio 2", "Audio 3"])       # ours goes last
        self.assertEqual((validate_project(self.moved), regressions(self.base, self.moved)), ([], []))

    def test_the_other_tracks_keep_their_routing(self):
        for name in ("Sum A", "Audio 1", "Audio 2"):
            self.assertEqual(track(self.moved, name), track(self.base, name))

    def test_logics_drag_out_keeps_the_bus(self):
        """Read only: a track dragged out of a summing stack stays routed to its bus."""
        out = project_data(_goldens.path(DRAGGED_OUT))
        self.assertEqual((track(out, "Audio 3")["depth"], track(out, "Audio 3")["output"]),
                         (_goldens.fact(DRAGGED_OUT, "depth"), _goldens.fact(DRAGGED_OUT, "output")))

    def test_logic_kept_a_move_written_here(self):
        ours, logics = (project_data(_goldens.path(k)) for k in ("stack-summing-move-ours", "stack-summing-move-resave-logic"))
        self.assertEqual(whole(logics)["rows"], whole(ours)["rows"])
        self.assertEqual(whole(logics)["stacks"], whole(ours)["stacks"])
        self.assertEqual({k: v[:4] for k, v in whole(logics)["routes"].items()}, {k: v[:4] for k, v in whole(ours)["routes"].items()})
        self.assertEqual(track(logics, "Audio 3"), track(self.moved, "Audio 3"))
        (stack,) = read_stacks(logics)
        self.assertEqual([n for _k, n in stack.members], _goldens.fact("stack-summing-move-resave-logic", "members"))

    def test_logics_convert_reads_as_a_summing_stack(self):
        """Read only: Convert Folder Stack to Summing Stack replaces the header; it is not written here."""
        key = "stack-converted-to-summing-logic"
        if _goldens.path(key) is None:
            self.skipTest("public corpus not present")
        data = project_data(_goldens.path(key))
        (stack,) = read_stacks(data)
        self.assertEqual([stack.name, stack.strip, input_labels(data)[stack.owner]], _goldens.fact(key, "header"))
        self.assertEqual([n for _k, n in stack.members], _goldens.fact(key, "members"))
        self.assertEqual({track(data, n)["stack_index"] for n in _goldens.fact(key, "members")},
                         {_goldens.fact(key, "member_stack_index")})
        sub = next(c for c in channels(data).values() if c.label == "Sub 1")
        self.assertEqual(sub.in_use, _goldens.fact(key, "sub_1_in_use"))

    def test_a_stack_is_not_moved_into_a_summing_stack(self):
        from logicxkit.logic.services.arrange.stack_moves import move_to_stack
        data, report = create_stack(self.base, name="Folder", members=[self.objs["Audio 3"]])
        with self.assertRaisesRegex(ValueError, "a stack moved into a summing stack"):
            move_to_stack(data, report["object_id"], self.objs["Sum A"])


if __name__ == "__main__":
    unittest.main()
