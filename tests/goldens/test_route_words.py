"""A written route says the same thing in its words as in its UUIDs, as Logic's re-save of one
does (`route-b01-resave`). Skips without the public corpus."""

import unittest

import _goldens

from logicxkit.logic.services.arrange.addtrack import add_track
from logicxkit.logic.services.mixer.binding import _input_by_word, _output_by_word, channels, input_labels, output_labels
from logicxkit.logic.services.arrange.environment import channel_objects
from logicxkit.logic.services.mixer.mixer import device_inputs
from logicxkit.logic.services.mixer.routing import set_input, set_output
from logicxkit.logicx import project_data

THREE = "nest-three-audio-logic"


def said_both_ways(data: bytes, owner: int) -> tuple:
    c, n = channels(data)[owner], device_inputs(data)
    return ((output_labels(data)[owner], input_labels(data)[owner]),
            (_output_by_word(c, n), _input_by_word(c, n)[1]))


@_goldens.needs(THREE)
class RouteWordsTest(unittest.TestCase):
    def setUp(self):
        self.data = project_data(_goldens.path(THREE))
        self.by_label = {c.label: o for o, c in channels(self.data).items()}

    def test_route_writes_the_words_its_uuids_name(self):
        audio = self.by_label["Audio 1"]
        out = set_output(self.data, audio, self.by_label["Bus 4"])
        out = set_input(out, audio, self.by_label["Input 2"])
        uuids, words = said_both_ways(out, audio)
        self.assertEqual(uuids, ("Bus 4", "Input 2"))
        self.assertEqual(words, uuids)
        out = set_input(set_output(out, audio, self.by_label["Output 1-2"]), audio, None)
        self.assertEqual(said_both_ways(out, audio), (("Output 1-2", None), ("Output 1-2", None)))

    def test_a_track_add_writes_the_words_its_uuids_name(self):
        anchor = next(i for i, o in channel_objects(self.data).items() if o.name == "Audio 3")
        out, report = add_track(self.data, name="Extra", after=anchor, input_number=2)
        uuids, words = said_both_ways(out, report["owner"])
        self.assertEqual(uuids, ("Output 1-2", "Input 2"))
        self.assertEqual(words, uuids)


@_goldens.needs("stack-folder-flattened-logic", "route-resave-logic")
class LogicsResavedRouteTest(unittest.TestCase):
    def test_route_writes_the_channel_record_logic_saved_but_its_version_word(self):
        from logicxkit.logic.services.mixer.mixer import is_mixer_record
        from logicxkit.logic.services.stream.stream import HEADER, project_records

        def record(data: bytes) -> bytearray:
            own = next(o for o, c in channels(data).items() if c.label == "Audio 2")
            raw = bytearray(max((r.raw for r in project_records(data) if is_mixer_record(r) and r.owner == own), key=len))
            raw[HEADER + 42] = 0                          # the word Logic 12.4's save sets
            return raw

        base = project_data(_goldens.path("stack-folder-flattened-logic"))
        by_label = {c.label: o for o, c in channels(base).items()}
        ours = set_output(base, by_label["Audio 2"], by_label["Bus 1"])
        self.assertEqual(record(ours), record(project_data(_goldens.path("route-resave-logic"))))


if __name__ == "__main__":
    unittest.main()
