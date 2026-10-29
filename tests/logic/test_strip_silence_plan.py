"""The strip-silence orchestrator's own checks: an audio entry's piece number is two bytes, so a
file whose pieces would pass 65535 is refused before anything is cut; a kept edge within half a
tick of the region's own is the region's, since no trim can move it."""

import unittest

import _paths  # noqa: F401
from logicxkit.logic.orchestrators.strip_silence import RegionPlan, _kept, require_piece_room
from logicxkit.logic.services.regions.audio_regions import PIECE_LIMIT, AudioRegion


def plan(name: str, slot: int, kept: int, offset: int = 0, frames: int = 10_000_000) -> RegionPlan:
    region = AudioRegion("Vox", 1, name, 38400, frames, None, offset=offset, file_slot=slot)
    step = frames // max(kept, 1)
    keeps = [(offset + k * step, offset + k * step + step // 2) for k in range(kept)]
    return RegionPlan(region, ("audio", (slot, 0)), 15.66, 44100, keeps, -20.0, -50.0)


class PieceRoomTest(unittest.TestCase):
    def test_a_file_whose_pieces_would_pass_the_limit_is_refused_by_name(self):
        with self.assertRaisesRegex(ValueError, r"'Vox 1' .*65600.*65535.*--min-gap"):
            require_piece_room([plan("Vox 1", 160, 65601)], {160: 0})

    def test_the_files_existing_pieces_count_too(self):
        require_piece_room([plan("Gtr", 120, 65000)], {120: 535})
        with self.assertRaisesRegex(ValueError, "65535"):
            require_piece_room([plan("Gtr", 120, 65000)], {120: 537})

    def test_two_regions_on_one_file_share_its_numbers(self):
        with self.assertRaisesRegex(ValueError, "65535"):
            require_piece_room([plan("A", 120, 33000), plan("B", 120, 33000, offset=5_000_000)], {120: 0})
        require_piece_room([plan("A", 120, 33000), plan("B", 124, 33000)], {120: 0, 124: 0})

    def test_the_limit_is_the_entrys_two_bytes(self):
        self.assertEqual(PIECE_LIMIT, 65535)
        require_piece_room([plan("A", 120, 300)], {120: 0})                    # past a byte, well inside two
        require_piece_room([plan("A", 120, 65536)], {120: 0})                  # 65535 cuts: pieces 1..65535
        with self.assertRaisesRegex(ValueError, "65535"):
            require_piece_room([plan("A", 120, 65537)], {120: 0})
        require_piece_room([plan("A", 120, 35536)], {120: 30000})             # pieces 30001..65535 after the file's own
        with self.assertRaisesRegex(ValueError, "to 65536, past 65535"):
            require_piece_room([plan("A", 120, 35537)], {120: 30000})


class SubTickEdgeTest(unittest.TestCase):
    SPT = 22.97                     # frames per tick at 120 bpm, 44.1 kHz
    FRAMES = 1_000_000

    def kept(self, stretches):
        region = AudioRegion("Vox", 1, "take", 38400, self.FRAMES, None, offset=0, file_slot=120)
        return _kept(region, stretches, (0, 0), self.SPT)[0]

    def test_an_edge_within_half_a_tick_of_the_regions_is_the_regions(self):
        self.assertEqual(self.kept([(self.FRAMES - 11, self.FRAMES)]), [(0, self.FRAMES)])
        self.assertEqual(self.kept([(0, 11)]), [(0, self.FRAMES)])
        self.assertEqual(self.kept([(0, 11), (500_000, 600_000)]), [(0, 500_000), (600_000, self.FRAMES)])

    def test_an_edge_exactly_half_a_tick_in_is_the_regions_as_the_tick_rounds_to_it(self):
        region = AudioRegion("Vox", 1, "take", 38400, self.FRAMES, None, offset=0, file_slot=120)
        self.assertEqual(round(11 / 22.0), 0)
        self.assertEqual(_kept(region, [(11, self.FRAMES - 11)], (0, 0), 22.0)[0], [(0, self.FRAMES)])

    def test_an_edge_past_half_a_tick_is_cut(self):
        self.assertEqual(self.kept([(self.FRAMES - 12, self.FRAMES)]), [(0, self.FRAMES - 12)])
        self.assertEqual(self.kept([(0, 12)]), [(12, self.FRAMES)])

    def test_the_edges_are_the_regions_own_wherever_it_starts_in_its_file(self):
        region = AudioRegion("Vox", 1, "take", 38400, self.FRAMES, None, offset=1000, file_slot=120)
        end = 1000 + self.FRAMES
        kept = lambda stretches: _kept(region, stretches, (0, 0), self.SPT)[0]  # noqa: E731
        self.assertEqual(kept([(1000, 1011)]), [(1000, end)])
        self.assertEqual(kept([(end - 11, end)]), [(1000, end)])
        self.assertEqual(kept([(1000, 1012), (end - 12, end)]), [(1012, end - 12)])



class RecordFileTest(unittest.TestCase):
    def test_a_file_of_another_length_than_the_record_is_refused_whatever_its_name(self):
        from pathlib import Path
        from logicxkit.logic.orchestrators.strip_silence import _require_record
        from logicxkit.logic.services.regions.audio_regions import AudioFile
        from logicxkit.logic.services.regions.silence import Envelope
        record = AudioFile("take.wav", "", 0, "WAVE", 44, 441000, 44100, 1, 24)
        region = AudioRegion("Vox", 1, "renamed", 38400, 441000, record)
        with self.assertRaisesRegex(ValueError, "renamed.wav holds 220500 frames .* it is not the file the project plays"):
            _require_record(Path("renamed.wav"), Envelope([], 441, 44100, 220500), region)
        _require_record(Path("renamed.wav"), Envelope([], 441, 44100, 441000), region)

if __name__ == "__main__":
    unittest.main()
