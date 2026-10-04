"""Logic 12.4's re-save of each copy written over a bus (2026-10-03): a summing stack by each of
its three rules, a convert reusing the bus's aux and one over mixed outputs, `route` and `send`
to a bus nothing used. Each opened without an alert and came back as written. Skips without the
public corpus."""

import unittest

import _goldens
from goldens.test_summing_outputs import channel_records, obj, shape

from logicxkit.logic.services.arrange.bus_return import use_bus
from logicxkit.logic.services.arrange.stack_convert import convert_to_summing
from logicxkit.logic.services.arrange.stack_summing import create_summing_stack
from logicxkit.logic.services.mixer.binding import channels
from logicxkit.logic.services.mixer.routing import set_output
from logicxkit.logic.services.mixer.sends import read_sends
from logicxkit.logic.services.mixer.sends_write import add_send
from logicxkit.logic.services.project.project import project_metadata
from logicxkit.logic.services.stream.table_index import index_errors
from logicxkit.logic.services.stream.stream import project_records
from logicxkit.logic.services.stream.validate import validate_project
from logicxkit.logicx import project_data

STACKS = ("stack-summing-shared", "stack-summing-differ", "stack-summing-reuse", "stack-convert-reuse",
          "stack-convert-differ")
ON_12_3_1 = ("route-bus", "send-bus")           # written on a Logic 12.3.1 save
VERSION_WORD = range(42, 44)                    # the word Logic 12.4 sets on every channel record
CLICK = "Inst 1"                                # its record moves between Logic's own saves


def load(key: str) -> tuple[bytes, int]:
    bundle = _goldens.path(key)
    return project_data(bundle), project_metadata(bundle)["tracks"]


def _owner(data: bytes, label: str) -> int:
    return next(o for o, c in channels(data).items() if c.label == label)


def _stacked(source: str, members: tuple[str, ...]) -> tuple[bytes, int]:
    data, count = load(source)
    out, report = create_summing_stack(data, name="S", members=[obj(data, m) for m in members], track_count=count)
    return out, count + report["tracks_added"]


def _converted(source: str) -> tuple[bytes, int]:
    data, count = load(source)
    out, report = convert_to_summing(data, obj(data, "Sub 1"), track_count=count)
    return out, count + report["tracks_added"]


def _on_a_bus(send: bool) -> tuple[bytes, int]:
    data, count = load("tracks-three-audio-logic")
    out, _report = use_bus(data, _owner(data, "Bus 1"), track_count=count)
    if send:
        return add_send(out, owner=_owner(out, "Audio 1"), bus=1, key=None)[0], count
    return set_output(out, _owner(out, "Audio 1"), _owner(out, "Bus 1")), count


WRITTEN = {
    "stack-summing-shared": lambda: _stacked("stack-summing-shared-before-logic", ("Audio 1", "Audio 2")),
    "stack-summing-differ": lambda: _stacked("route-out-bus-second-logic", ("Audio 1", "Audio 2", "Audio 3")),
    "stack-summing-reuse": lambda: _stacked("route-out-bus-second-logic", ("Audio 1", "Audio 2")),
    "stack-convert-reuse": lambda: _converted("stack-convert-reuse-track-before-logic"),
    "stack-convert-differ": lambda: _converted("stack-convert-differ-before-logic"),
    "route-bus": lambda: _on_a_bus(send=False),
    "send-bus": lambda: _on_a_bus(send=True),
}


def changed(ours: bytes, logic: bytes, *, masked=()) -> set[str]:
    """Labels of the channels whose record Logic's save changed, ``masked`` offsets aside."""
    def told(raw: bytes) -> bytes:
        return bytes(b for i, b in enumerate(raw) if i not in masked)
    was, now = channel_records(ours), channel_records(logic)
    return {channels(logic)[o].label for o in now if told(now[o]) != told(was.get(o, b""))}


@_goldens.needs(*(f"{k}-{side}" for k in STACKS + ON_12_3_1 for side in ("ours", "resave-logic")))
class LogicResavedTest(unittest.TestCase):
    def test_every_row_route_stack_and_index_came_back_as_written(self):
        for key in STACKS + ON_12_3_1:
            with self.subTest(key):
                (ours, count), (logic, logic_count) = load(f"{key}-ours"), load(f"{key}-resave-logic")
                self.assertEqual((count, shape(ours, count)), (logic_count, shape(logic, logic_count)))
                self.assertEqual((index_errors(project_records(ours), count), validate_project(logic)), ([], []))

    def test_logic_changed_no_channel_record_but_the_clicks(self):
        for key in STACKS:
            with self.subTest(key):
                self.assertLessEqual(changed(load(f"{key}-ours")[0], load(f"{key}-resave-logic")[0]), {CLICK})

    def test_on_a_12_3_1_project_it_changed_its_version_word_alone(self):
        for key in ON_12_3_1:
            with self.subTest(key):
                self.assertLessEqual(changed(load(f"{key}-ours")[0], load(f"{key}-resave-logic")[0], masked=VERSION_WORD), {CLICK})

    def test_the_writers_still_make_what_logic_opened(self):
        """Each staged copy made again in memory: every row, route, stack, index and channel
        record as the copy Logic opened, the minted ids aside."""
        for key, make in WRITTEN.items():
            with self.subTest(key):
                staged, staged_count = load(f"{key}-ours")
                out, count = make()
                self.assertEqual((count, shape(out, count)), (staged_count, shape(staged, staged_count)))
                self.assertEqual(channel_records(out, like=staged), channel_records(staged))

    def test_the_send_and_the_aux_it_brought_in_are_there(self):
        logic, _count = load("send-bus-resave-logic")
        sends = {channels(logic)[o].label: [s.bus for s in found] for o, found in read_sends(logic).items()}
        self.assertEqual(sends, {"Audio 1": [1]})


if __name__ == "__main__":
    unittest.main()
