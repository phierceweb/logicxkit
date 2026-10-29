"""A region whose flex markers are the two anchors of an identity map — source 0 to target 0, its
last frame to its length in ticks, as a bounced region on a flexed track carries — can be split
and trimmed: each piece gets the two anchors for its own length. Blocks after the anchors that
are not quantize hits (kinds 0 and 6) are the file's markers relative to the region start, and
travel with each piece shifted by its new offset. A region with a hit marker is still refused."""

import unittest

import _goldens
from _cli import count, data

from logicxkit.logic.services.regions.audio_regions import read_audio_regions
from logicxkit.logic.services.regions.flexmarkers import END, HIT, START, block_fields, marker_block, ticks_of
from logicxkit.logic.services.regions.region_edit import split_region, trim_region
from logicxkit.logic.services.regions.region_entry import identity_anchors
from logicxkit.logic.services.regions.region_locate import listed, samples_per_tick_of
from logicxkit.logic.services.regions.regions import ENTRY, entry_blocks, song_container
from logicxkit.logic.services.arrange.tracklist import arrange_run
from logicxkit.logic.services.stream.recbuild import rec
from logicxkit.logic.services.stream.stream import HEADER, project_records, reassemble
from logicxkit.logic.services.stream.validate import require_valid

BASE = "regions-a00-base-logic"          # region 1 is MIDI; 2, 3 and 4 are audio
RATE = 44100
FILE_END = 6                             # the kind Logic writes past the end anchor on a bounced file


def with_blocks(project: bytes, n: int | None, at: int, blocks: bytes) -> bytes:
    """``project`` with ``blocks`` appended to the song-container entry at ``at``."""
    records = project_records(project)
    song = song_container(records, arrange_run(records, n))
    payload = records[song.end].raw[HEADER:]
    out = [r.raw for r in records]
    out[song.end] = rec(b"qSvE", records[song.end].raw, payload[:at + ENTRY] + blocks + payload[at + ENTRY:])
    return reassemble(project, out)


def blocks_of(project: bytes, n: int | None) -> dict[int, list[tuple[int, int, int, int]]]:
    """Entry offset -> its marker blocks' (source, target, kind, fraction)."""
    records = project_records(project)
    song = song_container(records, arrange_run(records, n))
    payload = records[song.end].raw[HEADER:]
    out = {}
    for at, k in entry_blocks(payload):
        out[at] = [block_fields(payload[at + ENTRY * (i + 1):at + ENTRY * (i + 2)]) for i in range(k)]
    return out


@_goldens.needs(BASE)
class FlexAnchorsTest(unittest.TestCase):
    def setUp(self):
        self.n = count(BASE)
        base = data(BASE)
        self.spt = samples_per_tick_of(base, RATE)
        self.loc = next(x for x in listed(base, self.n) if x.audio)
        self.project = with_blocks(base, self.n, self.loc.audio.at, b"".join(identity_anchors(self.loc.audio.frames, self.spt)))

    def anchors_match(self, blocks, frames):
        ticks, fraction = ticks_of(frames, self.spt)
        self.assertEqual(blocks, [(0, START, 0, 0), (frames, END, ticks, fraction)])        # (source, kind, target, fraction)

    def test_the_anchors_are_an_identity_map_of_the_regions_length(self):
        start, end = identity_anchors(1000, self.spt)
        self.assertEqual(block_fields(start), (0, START, 0, 0))
        self.assertEqual(block_fields(end), (1000, END, *ticks_of(1000, self.spt)))
        self.assertEqual(blocks_of(self.project, self.n)[self.loc.audio.at][0], (0, START, 0, 0))

    def test_the_anchor_bytes_are_pinned_for_one_length(self):
        """The two blocks for 1000 frames at this golden's tempo, byte for byte: the start anchor's kind
        0x07 at `+6` under the 0xAA mark, the end anchor's source 1000 at `+0`, kind 0x03, the
        tick fraction 35220 at `+10` and 43 ticks at `+12`, the 0x88 flag words after."""
        self.assertEqual(self.spt, 22.96875)
        start, end = identity_anchors(1000, self.spt)
        self.assertEqual(start.hex(), "00000000000007aa00000000000000000000000000000088" + "00000000000000000000000000000088" * 3 + "0000000000000000")
        self.assertEqual(end.hex(), "e8030000000003aa000094892b0000000000000000000088" + "00000000000000000000000000000088" * 3 + "0000000000000000")

    def test_a_split_gives_each_piece_its_own_anchors(self):
        region = self.loc.audio
        cut = region.start + round(region.frames / 3 / self.spt)
        after = split_region(self.project, self.loc.number, cut, spt=self.spt, track_count=self.n)
        require_valid(after)
        pieces = sorted((r for r in read_audio_regions(after, self.n) if r.track == region.track), key=lambda r: r.start)
        self.assertEqual(len(pieces), 2)
        self.assertEqual(pieces[0].frames + pieces[1].frames, region.frames)
        blocks = blocks_of(after, self.n)
        for piece in pieces:
            self.anchors_match(blocks[piece.at], piece.frames)

    def test_a_trim_at_either_end_re_anchors_the_region(self):
        region = self.loc.audio
        shorter = trim_region(self.project, self.loc.number, length=round(region.frames / 2 / self.spt), spt=self.spt, track_count=self.n)
        later = trim_region(self.project, self.loc.number, start=region.start + 200, spt=self.spt, track_count=self.n)
        for project in (shorter, later):
            require_valid(project)
            (piece,) = [r for r in read_audio_regions(project, self.n) if r.track == region.track]
            self.anchors_match(blocks_of(project, self.n)[piece.at], piece.frames)
            self.assertLess(piece.frames, region.frames)

    def test_blocks_past_the_anchors_travel_with_each_piece_shifted_by_its_offset(self):
        region = self.loc.audio
        beyond = region.frames + 1000
        ticks, fraction = ticks_of(beyond, self.spt)
        extra = marker_block(beyond, ticks, FILE_END, fraction)
        start, end = identity_anchors(region.frames, self.spt)
        project = with_blocks(data(BASE), self.n, region.at, start + end + extra)
        cut = region.start + round(region.frames / 3 / self.spt)
        after = split_region(project, self.loc.number, cut, spt=self.spt, track_count=self.n)
        require_valid(after)
        first, second = sorted((r for r in read_audio_regions(after, self.n) if r.track == region.track), key=lambda r: r.start)
        blocks = blocks_of(after, self.n)
        self.assertEqual(blocks[first.at][2], (beyond, FILE_END, *ticks_of(beyond, self.spt)))             # the parent keeps its offset
        shifted = beyond - second.offset + region.offset
        self.assertEqual(blocks[second.at][2], (shifted, FILE_END, *ticks_of(shifted, self.spt)))        # the piece, from its own start
        self.assertEqual([b[1] for b in blocks[second.at]], [START, END, FILE_END])
        later = trim_region(project, self.loc.number, start=region.start + 200, spt=self.spt, track_count=self.n)
        (piece,) = [r for r in read_audio_regions(later, self.n) if r.track == region.track]
        moved = piece.offset - region.offset
        self.assertEqual(blocks_of(later, self.n)[piece.at][2], (beyond - moved, FILE_END, *ticks_of(beyond - moved, self.spt)))

    def test_a_region_with_a_hit_marker_is_still_refused(self):
        hit = marker_block(1000, 500, HIT)
        start, end = identity_anchors(self.loc.audio.frames, self.spt)
        project = with_blocks(data(BASE), self.n, self.loc.audio.at, start + hit + end)
        with self.assertRaisesRegex(ValueError, "flexed"):
            split_region(project, self.loc.number, self.loc.audio.start + 1000, spt=self.spt, track_count=self.n)


if __name__ == "__main__":
    unittest.main()
