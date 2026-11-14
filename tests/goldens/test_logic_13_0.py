"""Logic Pro 13.0 (7801)'s re-save of a public 12.3.1 blank (`tracks-two-audio-13-0-logic` from
`tracks-two-audio-logic`, opened and saved with no change): format word 2514; every channel
object's type word 488 lower (1800 -> 1312) at the same class; new `gnnT` and `ktSU` records; `MroC`
and the registry larger; the instrument channel's record 20 bytes longer with two keyed records
it did not carry. The readers find the same objects and rows; every writer refuses the format."""

import contextlib
import io
import struct
import tempfile
import unittest
from collections import Counter
from pathlib import Path

import _goldens

from logicxkit.cli import main as logicxkit_main
from logicxkit.logic.services.arrange.environment import NAME_AT, channel_objects
from logicxkit.logic.services.arrange.stacks import read_tracks
from logicxkit.logic.services.mixer.binding import channels
from logicxkit.logic.services.mixer.mixer import CHANNEL_TAG
from logicxkit.logic.services.stream.stream import HEADER, project_records
from logicxkit.logic.services.stream.validate import SAVED_BY, file_format
from logicxkit.logicx import project_data

BASE, NEW = "tracks-two-audio-logic", "tracks-two-audio-13-0-logic"
TYPE_DROP = 488


@_goldens.needs(BASE, NEW)
class Logic13Test(unittest.TestCase):
    def setUp(self):
        self.base, self.new = project_data(_goldens.path(BASE)), project_data(_goldens.path(NEW))

    def test_the_format_word_names_logic_13(self):
        self.assertEqual((file_format(self.base), file_format(self.new)), (2513, _goldens.fact(NEW, "format")))
        self.assertEqual(SAVED_BY[file_format(self.new)], "Logic 13.0")

    def test_a_writer_refuses_the_save_naming_logic_13(self):
        """A row that does not name Logic 13.0's format (`width`, held at 12.3.1's) refuses the save."""
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = logicxkit_main(["logic", "width", str(_goldens.path(NEW)), "--stereo", "Audio 1", "--out", tmp])
            self.assertNotEqual(code, 0)
            self.assertEqual(list(Path(tmp).glob("*.logicx")), [])
        self.assertIn("saved by Logic 13.0 (file format 2514", out.getvalue())

    def test_the_readers_find_the_same_objects_and_rows(self):
        names = lambda d: sorted(o.name for o in channel_objects(d).values())  # noqa: E731
        self.assertEqual(names(self.new), names(self.base))
        count = _goldens.fact(NEW, "tracks")
        self.assertEqual([(t["name"], t["label"]) for t in read_tracks(self.new, count)],
                         [(t["name"], t["label"]) for t in read_tracks(self.base, count)])
        self.assertEqual({c.label for c in channels(self.new).values()}, {c.label for c in channels(self.base).values()})

    def test_every_object_type_word_dropped_by_488(self):
        def words(d):
            return {r.raw[HEADER + NAME_AT + 2:HEADER + NAME_AT + 14]: struct.unpack_from("<I", r.raw, HEADER)[0] & 0xFFFF
                    for r in project_records(d) if r.tag == b"ivnE"}
        before, after = words(self.base), words(self.new)
        self.assertEqual(set(before), set(after))
        self.assertEqual({k: before[k] - after[k] for k in before}, {k: TYPE_DROP for k in before})

    def test_what_the_re_save_added(self):
        before, after = Counter(r.tag for r in project_records(self.base)), Counter(r.tag for r in project_records(self.new))
        self.assertEqual((before[b"gnnT"], after[b"gnnT"], before[b"ktSU"], after[b"ktSU"]), (0, 1, 0, 1))
        size = lambda d, tag: max(len(r.raw) for r in project_records(d) if r.tag == tag)  # noqa: E731
        self.assertGreater(size(self.new, b"MroC"), size(self.base, b"MroC"))
        self.assertGreater(size(self.new, b"gnoS"), size(self.base, b"gnoS"))
        inst = next(o for o, c in channels(self.base).items() if c.label == "Inst 1")
        record = lambda d: max((r.raw for r in project_records(d) if r.tag == CHANNEL_TAG and r.owner == inst), key=len)  # noqa: E731
        self.assertEqual(len(record(self.new)) - len(record(self.base)), 20)
        keyed = lambda d: [r.key for r in project_records(d) if r.tag == b"UCuA" and r.owner == inst]  # noqa: E731
        self.assertEqual((keyed(self.base), keyed(self.new)), ([2], [2, 7, 8]))


if __name__ == "__main__":
    unittest.main()
