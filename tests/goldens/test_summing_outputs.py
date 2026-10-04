"""A summing stack over members that go to a bus, against Logic 12.4's own Create Track Stack…
(Summing) and Convert Folder Stack to Summing Stack: a new aux outputs where every member did, or
to Output 1-2 when they differ, and members that are all a bus has make that bus's own aux the
main track. Every channel record is Logic's but for the minted ids. Skips without the public
corpus."""

import unittest

import _goldens
from logicxkit.logic.services.arrange.environment import channel_objects
from logicxkit.logic.services.arrange.stack_convert import convert_to_summing
from logicxkit.logic.services.arrange.stack_summing import create_summing_stack
from logicxkit.logic.services.arrange.stacks import read_stacks, read_tracks
from logicxkit.logic.services.arrange.tracklist import ROW_WORD_AT, arrange_run, flat_run, row_object
from logicxkit.logic.services.mixer.binding import channels, input_labels, output_labels
from logicxkit.logic.services.mixer.mixer import is_mixer_record
from logicxkit.logic.services.project.project import project_metadata
from logicxkit.logic.services.stream.sequence import index_table, table_entries
from logicxkit.logic.services.stream.stream import HEADER, project_records
from logicxkit.logic.services.stream.validate import validate_project
from logicxkit.logicx import project_data

# (Logic's save before, the members selected, Logic's save after)
CREATED = (
    ("stack-summing-shared-before-logic", ("Audio 1", "Audio 2"), "stack-summing-shared-after-logic"),
    ("route-out-bus-second-logic", ("Audio 1", "Audio 2", "Audio 3"), "stack-summing-differ-logic"),
    ("nest-summing-in-summing-before-logic", ("Audio 2", "Audio 3"), "nest-summing-in-summing-after-logic"),
    ("nest-summing-in-summing-differ-before-logic", ("Audio 2", "Audio 3"), "nest-summing-in-summing-differ-after-logic"),
    ("stack-summing-placeholder-before-logic", ("Audio 1", "Audio 2"), "stack-summing-placeholder-after-logic"),
)
CONVERTED = (("stack-convert-differ-before-logic", "Sub 1", "stack-convert-differ-after-logic"),)
# (Logic's save before, the members or the folder, Logic's save after): the bus's own aux reused
REUSED = (
    ("route-out-bus-second-logic", ("Audio 1", "Audio 2"), "stack-summing-reuse-logic"),
    ("tracks-aux-track-logic", ("Audio 1", "Audio 2", "Audio 3"), "stack-summing-reuse-track-logic"),
    ("stack-summing-reuse-colour-before-logic", ("Audio 1", "Audio 2", "Audio 3"), "stack-summing-reuse-colour-after-logic"),
    ("stack-convert-reuse-before-logic", "Sub 1", "stack-convert-reuse-after-logic"),
    ("stack-convert-reuse-track-before-logic", "Sub 1", "stack-convert-reuse-track-after-logic"),
    ("stack-convert-reuse-named-before-logic", "Drums", "stack-convert-reuse-named-after-logic"),
)
STATE = tuple(f"stack-convert-reuse-{tag}-{side}-logic" for tag in ("level", "lane", "both", "auxlane")
              for side in ("before", "after"))
KEYS = sorted({k for case in CREATED + CONVERTED + REUSED for k in (case[0], case[2])} | set(STATE))


def load(key: str) -> tuple[bytes, int]:
    bundle = _goldens.path(key)
    return project_data(bundle), project_metadata(bundle)["tracks"]


def obj(data: bytes, name: str) -> int:
    return next(i for i, o in channel_objects(data).items() if o.name == name)


def routing(data: bytes) -> dict[str, tuple]:
    ins, outs = input_labels(data), output_labels(data)
    return {c.label: (ins.get(o), outs.get(o)) for o, c in channels(data).items() if c.in_use}


def shape(data: bytes, count: int) -> dict:
    """What a summing stack changes: the rows, the stacks, every channel in use and its routing,
    each arranged track's parent and colour, the mixer-order list (None for an object that is
    gone) and each index-table entry's place in it."""
    objects = channel_objects(data)
    rows = read_tracks(data, count)
    records = project_records(data)
    named = lambda o: objects[o].name if o in objects else None                  # noqa: E731
    return {"rows": [(r["name"], r["label"], r["depth"]) for r in rows],
            "flat": [named(row_object(records[i].raw)) for i in flat_run(records, arrange_run(records, count))],
            "table": sorted(((named(e[1]) or ""), e[2]) for e in table_entries(records[index_table(records)].raw[HEADER:])),
            "stacks": [(s.name, s.kind, s.strip, s.depth, [n for _k, n in s.members]) for s in read_stacks(data, count)],
            "routing": routing(data),
            "objects": {r["name"]: (objects[o.parent].name if o.parent else None, o.colour)
                        for r in rows if (o := objects.get(r["object_id"])) is not None}}


def channel_records(data: bytes, like: bytes | None = None) -> dict[int, bytes]:
    """owner -> channel record; with ``like``, each channel's own UUID told as ``like``'s (a
    minted id is random on both sides)."""
    found = {r.owner: r.raw[HEADER:] for r in project_records(data) if is_mixer_record(r)}
    if like is not None:
        mine, theirs = channels(data), channels(like)
        told = {mine[o].uuid: theirs[o].uuid for o in mine if o in theirs and mine[o].uuid != theirs[o].uuid}
        for owner, raw in found.items():
            for uuid, as_logic in told.items():
                raw = raw.replace(uuid, as_logic)
            found[owner] = raw
    return found


@_goldens.needs(*KEYS)
class SummingOutputsTest(unittest.TestCase):
    def assert_channels_as_logics(self, before: bytes, ours: bytes, logic: bytes) -> None:
        """Every channel record the write changed is Logic's byte for byte, and Logic changed no
        other but the Click's (`Inst 1`, a byte that moves between its own saves)."""
        was, mine, theirs = channel_records(before), channel_records(ours, like=logic), channel_records(logic)
        written = {o for o, raw in channel_records(ours).items() if raw != was.get(o)}
        self.assertEqual({o: mine[o] for o in written}, {o: theirs.get(o) for o in written})
        only_logic = {channels(logic)[o].label for o, raw in theirs.items() if raw != was.get(o)} - \
                     {channels(ours)[o].label for o in written}
        self.assertLessEqual(only_logic, {"Inst 1"})

    def test_logics_saves_read_as_their_facts_say(self):
        for key in KEYS:
            data, count = load(key)
            name, strip, members = _goldens.fact(key, "stack") or (None, None, None)
            with self.subTest(key=key):
                if name is not None:
                    found = [(s.name, s.strip, [n for _k, n in s.members]) for s in read_stacks(data, count)]
                    self.assertIn((name, strip, members), found)
                outs = {label: out for label, (_i, out) in routing(data).items()}
                for label, out in (_goldens.fact(key, "outputs") or {}).items():
                    self.assertEqual((label, outs.get(label)), (label, out))
                if _goldens.fact(key, "tracks") is not None:
                    self.assertEqual(count, _goldens.fact(key, "tracks"))
                colours = {o.name: o.colour for o in channel_objects(data).values()}
                for name, colour in (_goldens.fact(key, "colours") or {}).items():
                    self.assertEqual((name, colours.get(name)), (name, colour))

    def test_a_header_row_patterned_on_an_audio_row_carries_an_aux_rows_word(self):
        """`route-out-bus-second-logic` has its one aux in use with no arrange row, so the new
        header's row is shaped on an audio row; Logic's own header row has 0 at `+52`."""
        def word(data: bytes, count: int, name: str) -> bytes:
            records = project_records(data)
            stack = next(s for s in read_stacks(data, count) if s.name == name)
            row = next(records[i].raw for i in arrange_run(records, count) if row_object(records[i].raw) == stack.object_id)
            return row[HEADER + ROW_WORD_AT:HEADER + ROW_WORD_AT + 4]
        data, count = load("route-out-bus-second-logic")
        out, _report = create_summing_stack(data, name="S", members=[obj(data, f"Audio {n}") for n in (1, 2, 3)], track_count=count)
        logic, logic_count = load("stack-summing-differ-logic")
        name = _goldens.fact("stack-summing-differ-logic", "stack")[0]
        self.assertEqual((word(out, count + 1, "S"), word(logic, logic_count, name)), (bytes(4), bytes(4)))

    def test_our_stack_reads_as_logics_own(self):
        for before, members, after in CREATED:
            with self.subTest(after=after):
                data, count = load(before)
                logic, logic_count = load(after)
                name = _goldens.fact(after, "stack")[0]
                out, report = create_summing_stack(data, name=name, members=[obj(data, m) for m in members],
                                                   track_count=count)
                self.assertEqual(shape(out, count + 1), shape(logic, logic_count))
                self.assertEqual((report["bus"], report["reused"], report["tracks_added"]),
                                 (_goldens.fact(after, "bus"), False, 1))
                self.assert_channels_as_logics(data, out, logic)
                self.assertEqual(validate_project(out), [])

    def test_our_convert_reads_as_logics_own(self):
        for before, folder, after in CONVERTED:
            with self.subTest(after=after):
                data, count = load(before)
                logic, logic_count = load(after)
                out, report = convert_to_summing(data, obj(data, folder), track_count=count)
                self.assertEqual(shape(out, count), shape(logic, logic_count))
                self.assertEqual(report["bus"], _goldens.fact(after, "bus"))
                self.assert_channels_as_logics(data, out, logic)
                self.assertEqual(validate_project(out), [])

    def test_the_report_names_where_the_stack_outputs_and_what_its_members_left(self):
        data, count = load("route-out-bus-second-logic")
        _out, report = create_summing_stack(data, name="Sum 2", members=[obj(data, f"Audio {n}") for n in (1, 2, 3)],
                                            track_count=count)
        self.assertEqual((report["output"], report["left"]), ("Output 1-2", {"Audio 1": "Bus 1", "Audio 2": "Bus 1"}))
        data, count = load("stack-summing-shared-before-logic")
        _out, report = create_summing_stack(data, name="Sum 2", members=[obj(data, f"Audio {n}") for n in (1, 2)],
                                            track_count=count)
        self.assertEqual((report["output"], report["left"]), ("Bus 1", {}))

    def test_members_that_are_all_a_bus_has_make_its_aux_the_main_track(self):
        for before, what, after in REUSED:
            with self.subTest(after=after):
                data, count = load(before)
                logic, logic_count = load(after)
                if isinstance(what, tuple):
                    out, report = create_summing_stack(data, name="S", members=[obj(data, m) for m in what],
                                                       track_count=count)
                else:
                    out, report = convert_to_summing(data, obj(data, what), track_count=count)
                self.assertEqual(count + report["tracks_added"], logic_count)
                self.assertEqual(shape(out, logic_count), shape(logic, logic_count))
                self.assertEqual((report["reused"], report["label"], report["bus"], report["left"]),
                                 (True, "Aux 1", "Bus 1", {}))
                self.assert_channels_as_logics(data, out, logic)
                self.assertEqual(validate_project(out), [])

    def test_a_place_no_save_shows_is_refused(self):
        """Every member of a summing stack is all its bus has, and the aux is that stack's own header."""
        data, count = load("nest-summing-in-summing-before-logic")
        with self.assertRaisesRegex(ValueError, "not measured"):
            create_summing_stack(data, name="S", members=[obj(data, f"Audio {n}") for n in (1, 2, 3)], track_count=count)

    def test_a_reused_aux_keeps_its_level_and_takes_the_folders_volume_lane(self):
        """As Logic's convert left them: the folder's level on the `Sub` strip it takes out of
        use, the aux at its own; the folder's Volume lane on the aux."""
        from logicxkit.logic.services.mixer.levels import read_levels
        from logicxkit.logic.services.regions.automation import read_automation

        def faders(data):
            return {c.label: round(read_levels(data)[o]["fader_db"], 1) for o, c in channels(data).items()
                    if c.label in ("Sub 1", "Aux 1")}

        def lanes(data, count):
            return sorted((a.track, ln.parameter, tuple((p.tick, p.value) for p in ln.points))
                          for a in read_automation(data, count) for ln in a.lanes)
        for tag in ("level", "lane", "both", "auxlane"):
            with self.subTest(tag):
                before, after = (f"stack-convert-reuse-{tag}-{side}-logic" for side in ("before", "after"))
                data, count = load(before)
                logic, logic_count = load(after)
                out, report = convert_to_summing(data, obj(data, "Sub 1"), track_count=count)
                self.assertEqual(shape(out, count + report["tracks_added"]), shape(logic, logic_count))
                self.assertEqual((faders(out), lanes(out, logic_count)), (faders(logic), lanes(logic, logic_count)))
                self.assert_channels_as_logics(data, out, logic)
                said = _goldens.fact(after, "lanes")
                if said is not None:                          # bars, as the fact gives them, to ticks
                    self.assertEqual(lanes(logic, logic_count), sorted(
                        (track, lane, tuple((38400 + 3840 * (bar - 1), float(v)) for bar, v in points))
                        for track, lane, points in said))
        self.assertEqual(faders(load("stack-convert-reuse-level-after-logic")[0]),
                         _goldens.fact("stack-convert-reuse-level-after-logic", "faders"))
        track, lane, points = _goldens.fact("stack-convert-reuse-lane-after-logic", "lane")
        logic, logic_count = load("stack-convert-reuse-lane-after-logic")
        self.assertEqual([(t, p, len(pts)) for t, p, pts in lanes(logic, logic_count)], [(track, lane, len(points))])

    def test_the_report_names_a_lane_the_folders_replaced(self):
        data, count = load("stack-convert-reuse-both-before-logic")
        _out, report = convert_to_summing(data, obj(data, "Sub 1"), track_count=count)
        self.assertEqual(report["lanes_replaced"], ["Volume"])

    def test_an_aux_with_another_lane_under_a_folder_with_a_volume_lane_is_refused(self):
        from logicxkit.logic.services.regions.automation import FADER_IDS
        from logicxkit.logic.services.regions.automation_write import set_lane
        data, count = load("stack-convert-reuse-both-before-logic")
        panned = set_lane(data, obj(data, "Aux 1"), FADER_IDS["Pan"], [(38400, 40)])
        with self.assertRaisesRegex(ValueError, "carries a Pan lane"):
            convert_to_summing(panned, obj(panned, "Sub 1"), track_count=count)


if __name__ == "__main__":
    unittest.main()
