"""An audio file skipped on open: Logic clears the byte after its `lFuA` record's `LFUA` magic, which
sits past the UTF-16 name, so the offset moves with the name's length (three names of three lengths
in `regions-c04-crossfade-split-logic`, all three present in `regions-a20-crossfade-logic`)."""

import unittest

import _goldens

from logicxkit.logic.services.regions.audio_regions import file_name, file_present
from logicxkit.logic.services.stream.stream import HEADER, project_records
from logicxkit.logicx import project_data

PRESENT, SKIPPED = "regions-a20-crossfade-logic", "regions-c04-crossfade-split-logic"


def files(key: str) -> dict[str, bool]:
    return {file_name(r.raw[HEADER:]): file_present(r.raw[HEADER:])
            for r in project_records(project_data(_goldens.path(key))) if r.tag == b"lFuA"}


@_goldens.needs(PRESENT, SKIPPED)
class SkippedFileTest(unittest.TestCase):
    def test_the_byte_after_the_magic_is_cleared_for_a_skipped_file(self):
        skipped = _goldens.fact(SKIPPED, "skipped_files")
        self.assertEqual(sorted(len(n) for n in skipped), [13, 14, 15])
        self.assertEqual(files(PRESENT), {n: True for n in skipped})
        self.assertEqual(files(SKIPPED), {n: False for n in skipped})


if __name__ == "__main__":
    unittest.main()
