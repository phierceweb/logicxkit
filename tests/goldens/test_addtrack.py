"""Adding a track. Measured against Logic's own adds on 2026-09-01 (those saves are gone); the
real-file golden now holds the output to the invariants every Logic file obeys.

The real-file part of tests/logic/test_addtrack.py; skips without the owner's files."""

import unittest
import _goldens
from logicxkit.logic.services.stacks import read_tracks
from logicxkit.logicx import project_data
import _paths
from _data import needs

MIX = _paths.staged("Mix")


@unittest.skipIf(not MIX.exists(), "the staged Mix template is not present")
@needs("logic", "inst-track-12.3.1.json", "aux-track-12.3.1.json")
class MixTemplateAddTest(unittest.TestCase):
    """A real Logic 12.3.1 project: the add must keep every measured invariant."""

    @classmethod
    def setUpClass(cls):
        from collections import Counter

        from _invariants import report
        from logicxkit.logic.services.project import project_metadata
        from logicxkit.logic.services.stacks import read_tracks
        from logicxkit.logicx import project_data
        cls.data = project_data(MIX)
        cls.count = project_metadata(MIX)["tracks"]
        rows = read_tracks(cls.data, cls.count)
        names = Counter(r["name"] for r in rows)
        cls.anchor = [r for r in rows if not r["member"] and not r["grouping"] and names[r["name"]] == 1][-1]
        cls.before = report(cls.data, cls.count)["link_errors"]

    def _check(self, out, report, kind):
        from _invariants import assert_consistent
        from logicxkit.logic.services.stacks import read_tracks
        assert_consistent(self, out, self.count + 1, selected=report["object_id"],
                          link_errors_before=self.before)
        rows = read_tracks(out, self.count + 1)
        self.assertEqual([r["key"] for r in rows], list(range(self.count + 2)))
        new = next(r for r in rows if r["object_id"] == report["object_id"])
        self.assertEqual((new["key"], new["member"], new["label"]),
                         (self.anchor["key"] + 1, False, report["label"]))
        self.assertTrue(new["label"].startswith("Audio " if kind == "audio" else "Inst "))

    def test_an_audio_track(self):
        from logicxkit.logic.services.addtrack import add_audio_track
        out, report = add_audio_track(self.data, name="Second Audio", after=self.anchor["object_id"],
                                      track_count=self.count)
        self.assertEqual(report["input"], "Input 1")
        self._check(out, report, "audio")

    def test_an_instrument_track_shifts_every_later_owner(self):
        from logicxkit.logic.services.addtrack import add_track
        from logicxkit.logic.services.binding import channels
        out, report = add_track(self.data, name="Second Inst", after=self.anchor["object_id"],
                                kind="instrument", track_count=self.count)
        self._check(out, report, "instrument")
        before, after = channels(self.data), channels(out)
        self.assertEqual(len(after), len(before) + 1)
        for owner, chan in before.items():
            if owner >= report["owner"] and not chan.label.startswith("Inst "):
                self.assertEqual(after[owner + 1].label, chan.label)


@_goldens.needs("tracks-three-audio-logic", "tracks-stereo-pair-logic")
class StereoPairInputTest(unittest.TestCase):
    """Logic's own New Tracks with Audio Input "Input 1-2" (an interface attached, 2026-09-17): the
    new track is stereo and its input is the pair channel; ours binds the same way."""

    @staticmethod
    def _audio4(data):
        from logicxkit.logic.services.binding import channels, input_routing
        from logicxkit.logic.services.mixer import channel_formats
        ch = channels(data)
        owner = next(o for o, c in ch.items() if c.label == "Audio 4")
        source = input_routing(data).get(owner)
        return channel_formats(data).get(owner), ch[source].label if source in ch else None

    def test_logics_save_binds_the_pair_channel(self):
        logic = project_data(_goldens.path("tracks-stereo-pair-logic"))
        self.assertEqual(self._audio4(logic), (_goldens.fact("tracks-stereo-pair-logic", "format"),
                                               _goldens.fact("tracks-stereo-pair-logic", "input")))
        self.assertEqual([r["name"] for r in read_tracks(logic)][:4], ["Audio 1", "Audio 2", "Audio 3", "Audio 4"])

    def test_ours_binds_the_pair_channel_like_logic(self):
        from logicxkit.logic.services.addtrack import add_track
        base = project_data(_goldens.path("tracks-three-audio-logic"))
        after = next(r["object_id"] for r in read_tracks(base) if r["name"] == "Audio 3")
        out, _report = add_track(base, name="Audio 4", after=after, stereo=True)
        self.assertEqual(self._audio4(out), (2, "Input 1-2"))
        with self.assertRaises(ValueError):
            add_track(base, name="Audio 4", after=after, stereo=True, input_number=2)


@_goldens.needs("tracks-three-audio-logic")
class NamelessObjectTest(unittest.TestCase):
    """An object whose name does not decode (one byte of `Stereo Out` put outside ASCII) is still
    bound, so the insert moves its stored index with its channel."""

    def test_the_index_of_a_nameless_bound_object_follows_its_channel(self):
        import struct

        from logicxkit.logic.services.addtrack import add_track
        from logicxkit.logic.services.binding import channels
        from logicxkit.logic.services.environment import NAME_AT, name_end, object_record
        from logicxkit.logic.services.stream import HEADER, project_records
        data = project_data(_goldens.path("tracks-three-audio-logic"))
        at = data.index(object_record(project_records(data), 80)) + HEADER + NAME_AT + 2
        data = data[:at] + b"\xfc" + data[at + 1:]
        out, _ = add_track(data, name="Keys", after=88, kind="instrument")
        obj = object_record(project_records(out), 80)
        owner = next(o for o, c in channels(out).items() if c.uuid == obj[-16:])
        index = struct.unpack_from("<H", obj, HEADER + name_end(obj[HEADER:]))[0]
        self.assertEqual(index, owner + 1)


if __name__ == "__main__":
    unittest.main()
