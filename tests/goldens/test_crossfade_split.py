"""`regions --split` on a crossfaded region against Logic's own split of it (Logic 13.0,
`regions-c04-crossfade-split-logic` from `regions-a20-crossfade-logic`): the same regions, and the
three entries on the track byte for byte — the parent keeps its crossfade bit and the edited and
selected bits move to the piece, which carries no crossfade; the partner is untouched. The region
records differ where 13.0's layout does; those bytes are not pinned."""

import tempfile
import unittest
from pathlib import Path

import _goldens

from logicxkit.cli import main as logicxkit_main
from logicxkit.logic.services.arrange.stacks import arrange_run
from logicxkit.logic.services.regions.audio_regions import read_audio_regions
from logicxkit.logic.services.regions.regions import ENTRY, song_container
from logicxkit.logic.services.stream.stream import HEADER, project_records
from logicxkit.logic.services.stream.validate import validate_project
from logicxkit.logicx import project_data

BASE, LOGICS = "regions-a20-crossfade-logic", "regions-c04-crossfade-split-logic"
TRACK_REGIONS = ("tone renamed", "v030-tone2.1", "v030-tone2.2")


def entries(data: bytes) -> dict[str, bytes]:
    records = project_records(data)
    payload = records[song_container(records, arrange_run(records, None)).end].raw[HEADER:]
    return {r.name: payload[r.at:r.at + ENTRY] for r in read_audio_regions(data)}


def shape(data: bytes) -> list[tuple]:
    return [(r.name, r.start, r.frames, r.offset, r.piece, r.crossfaded, r.fade) for r in read_audio_regions(data)]


@_goldens.needs(BASE, LOGICS)
class CrossfadeSplitTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        out = Path(self.tmp.name)
        code = logicxkit_main(["logic", "regions", str(_goldens.path(BASE)), "--split", "6=1.375", "--out", str(out)])
        self.assertEqual(code, 0)
        self.ours = project_data(out / _goldens.path(BASE).name)
        self.logics = project_data(_goldens.path(LOGICS))

    def test_the_regions_and_the_tracks_entries_are_logics(self):
        self.assertEqual(shape(self.ours), shape(self.logics))
        ours, logics = entries(self.ours), entries(self.logics)
        self.assertEqual({n: ours[n] for n in TRACK_REGIONS}, {n: logics[n] for n in TRACK_REGIONS})
        self.assertEqual(validate_project(self.ours), [])

    def test_the_piece_carries_no_crossfade_and_the_parent_keeps_its_bit(self):
        for data in (self.logics, self.ours):
            pieces = {r.name: r.crossfaded for r in read_audio_regions(data)}
            self.assertEqual((pieces["v030-tone2.1"], pieces["v030-tone2.2"], pieces["tone renamed"]), (True, False, True))


if __name__ == "__main__":
    unittest.main()
