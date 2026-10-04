"""An index-table entry's index is its object's place in the mixer-order track list: on every
Logic save on hand, and after every writer that adds a channel or a row. Off its place, Logic
re-lays the entry on load, and the sequence of an object with no arrange row goes to whichever
object holds that place. Skips without the public corpus."""

import unittest

import _goldens
from logicxkit.logic.services.arrange.addtrack import add_track
from logicxkit.logic.services.arrange.bus_return import use_bus
from logicxkit.logic.services.arrange.environment import channel_objects
from logicxkit.logic.services.arrange.stack_convert import convert_to_summing
from logicxkit.logic.services.arrange.stack_create import create_stack
from logicxkit.logic.services.arrange.stack_summing import create_summing_stack
from logicxkit.logic.services.mixer.binding import channels
from logicxkit.logic.services.project.project import project_metadata
from logicxkit.logic.services.stream.table_index import index_errors
from logicxkit.logic.services.stream.stream import project_records
from logicxkit.logicx import project_data

THREE, FOLDER, OURS = "tracks-three-audio-logic", "stack-folder-logic", "stack-summing-ours"


def load(key: str) -> tuple[bytes, int]:
    bundle = _goldens.path(key)
    return project_data(bundle), project_metadata(bundle)["tracks"]


def errors(data: bytes, count: int | None) -> list[str]:
    return index_errors(project_records(data), count)


class EveryLogicSaveTest(unittest.TestCase):
    def test_no_entry_is_off_its_place(self):
        keys = sorted(k for k, e in _goldens.manifest().items() if isinstance(e, dict)
                      and str(e.get("path", "")).endswith(".logicx") and "logic" in k.split("-"))
        saves = [(k, b) for k in keys if (b := _goldens.path(k)) is not None]
        if not saves:
            self.skipTest("no public corpus on this machine")
        off = {k: found for k, b in saves
               if (found := index_errors(project_records(project_data(b)), project_metadata(b).get("tracks")))}
        self.assertEqual(off, {})
        self.assertGreater(len(saves), 300)


@_goldens.needs(THREE, FOLDER, OURS)
class WritersTest(unittest.TestCase):
    def setUp(self):
        self.data, self.count = load(THREE)
        self.objects = {o.name: i for i, o in channel_objects(self.data).items()}

    def test_a_copy_written_without_the_rule_is_off(self):
        """The reader finds two headers one place low."""
        data, count = load(OURS)
        self.assertEqual(len(errors(data, count)), 2)

    def test_an_added_track_of_each_kind(self):
        for kind in ("audio", "instrument", "aux"):
            with self.subTest(kind):
                out, _r = add_track(self.data, name="New", after=self.objects["Audio 1"], kind=kind, track_count=self.count)
                self.assertEqual(errors(out, self.count + 1), [])

    def test_a_stack_of_each_kind(self):
        members = [self.objects["Audio 1"], self.objects["Audio 2"]]
        for make in (create_stack, create_summing_stack):
            with self.subTest(make.__name__):
                out, _r = make(self.data, name="S", members=members, track_count=self.count)
                self.assertEqual(errors(out, self.count + 1), [])

    def test_a_convert(self):
        data, count = load(FOLDER)
        folder = next(i for i, o in channel_objects(data).items() if o.name == "Sub 1")
        out, _r = convert_to_summing(data, folder, track_count=count)
        self.assertEqual(errors(out, count), [])

    def test_a_bus_put_in_use(self):
        bus = next(o for o, c in channels(self.data).items() if c.label == "Bus 1")
        out, _r = use_bus(self.data, bus, track_count=self.count)
        self.assertEqual(errors(out, self.count), [])


if __name__ == "__main__":
    unittest.main()
