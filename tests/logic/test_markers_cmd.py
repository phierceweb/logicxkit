"""`logic markers --add`: spec parsing (a name may hold colons), and ten markers through the gate."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _goldens
import _paths  # noqa: F401
from _cli import run, written
from logicxkit.logic._edit import CommandError, first_project_data
from logicxkit.logic._markers_cmd import parse_add
from logicxkit.logic.services.regions import audio_regions
from logicxkit.logic.services.song.arrangement_write import free_text_slot
from logicxkit.logic.services.song.markers import read_markers
from logicxkit.logic.services.song.markers_write import add_marker
from logicxkit.logic.services.stream.integrity_regions import dangling_files
from logicxkit.logic.services.stream.stream import project_records


class ParseAddTest(unittest.TestCase):
    def test_bar_bars_and_name_with_colons(self):
        self.assertEqual(parse_add("8:Bridge"), ("8", "", "Bridge"))
        self.assertEqual(parse_add("8:2:Bridge"), ("8", "2", "Bridge"))
        self.assertEqual(parse_add("8:Chorus: take 2"), ("8", "", "Chorus: take 2"))
        self.assertEqual(parse_add("8.5:2:A: B"), ("8.5", "2", "A: B"))
        self.assertEqual(parse_add("8:2:"), ("8", "", "2:"))
        for bad in ("8", "x:Name", ":Name", "8:"):
            with self.subTest(bad), self.assertRaises(CommandError):
                parse_add(bad)



BASE = "regions-a00-base-logic"


@_goldens.needs(BASE)
class TenMarkersTest(unittest.TestCase):
    """The marker track's events are 48 bytes; walked in 80-byte strides, a data line at byte 160
    or 400 (the fourth or ninth event) whose name slot is 36, `AUDIO_ENTRY`'s value, reads as a
    region entry. The gate's entry walk leaves the marker and arrangement tracks out."""

    def _ten_markers(self) -> bytes:
        """Ten markers, the one on name slot 36 placed ninth in tick order."""
        data = first_project_data(_goldens.path(BASE))
        first = free_text_slot(project_records(data))
        if first > 36 or first % 4:
            self.skipTest(f"the bundle's first free name slot is {first}; slot 36 is out of reach")
        order = list(range(10))                     # tick order by add number: slots go by add order
        hit = (36 - first) // 4                     # the add that takes slot 36
        order.remove(hit)
        order.insert(8, hit)                        # ninth in tick order
        for add in range(10):
            data = add_marker(data, f"Mark {add + 1}", tick=38400 + 3840 * 8 * (order.index(add) + 1), length=3840 * 4)
        self.assertEqual(read_markers(data)[8].text_slot, 36)
        return data

    def test_the_marker_track_is_not_walked_for_entries(self):
        before = len(audio_regions.audio_entry_pairs(project_records(first_project_data(_goldens.path(BASE)))))
        records = project_records(self._ten_markers())
        self.assertEqual(len(audio_regions.audio_entry_pairs(records)), before)
        self.assertEqual(dangling_files(records)["entries"], [])
        with mock.patch.object(audio_regions, "marker_sequence", lambda records: None), \
                mock.patch.object(audio_regions, "section_sequence", lambda records: None):
            self.assertEqual(len(audio_regions.audio_entry_pairs(records)), before + 1,
                             "walked, the slot-36 data line at byte 400 reads as an audio entry")

    def test_ten_markers_write_through_the_gate(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        adds = [a for k in range(10) for a in ("--add", f"{10 + 8 * k}:4:Mark {k + 1}")]
        dest = written(self, "markers", BASE, *adds, out=Path(tmp.name))
        code, text = run("markers", dest)
        self.assertEqual(code, 0, text)
        self.assertIn("10 marker(s)", text)

if __name__ == "__main__":
    unittest.main()
