"""The identity anchors a bounced region carries on a flexed track, in Logic's own saves of two live
sets: every audio entry whose first two marker blocks are a start and an end anchor holds the two
`identity_anchors` writes for its length — source 0 to tick 0, its last frame to its length in
ticks, the fraction within a few 65536ths on one set and within a tick's few percent on the other."""

import unittest

import _goldens

from logicxkit.logic._edit import first_project_data
from logicxkit.logic.services.arrange.tracklist import arrange_run
from logicxkit.logic.services.project.project import project_metadata
from logicxkit.logic.services.regions.audio_regions import AUDIO_ENTRY, read_audio_regions
from logicxkit.logic.services.regions.flexmarkers import END, START, block_fields
from logicxkit.logic.services.regions.region_entry import identity_anchors
from logicxkit.logic.services.regions.region_locate import samples_per_tick_of
from logicxkit.logic.services.regions.regions import ENTRY, entry_blocks, song_container
from logicxkit.logic.services.stream.stream import HEADER, project_records

KEYS = {"vocal-pieces-moved-logic": 2, "arrangement-gaps-resave": 2048}      # key -> fraction tolerance, in 65536ths


def anchored_entries(key: str):
    path = _goldens.path(key)
    data, meta = first_project_data(path), project_metadata(path)
    spt = samples_per_tick_of(data, meta["sample_rate"])
    records = project_records(data)
    payload = records[song_container(records, arrange_run(records, meta.get("tracks"))).end].raw[HEADER:]
    frames_at = {r.at: r.frames for r in read_audio_regions(data, meta.get("tracks"))}
    for at, k in entry_blocks(payload):
        if payload[at] != AUDIO_ENTRY or k < 2:
            continue
        blocks = [block_fields(payload[at + ENTRY * (i + 1):at + ENTRY * (i + 2)]) for i in range(2)]
        if blocks[0][1] == START and blocks[1][1] == END:
            yield spt, frames_at[at], blocks


@_goldens.needs(*KEYS)
class IdentityAnchorsTest(unittest.TestCase):
    def test_every_anchored_region_carries_the_two_blocks_the_writer_makes(self):
        for key, tolerance in KEYS.items():
            found = 0
            for spt, frames, (start, end) in anchored_entries(key):
                self.assertEqual(end[0], frames, key)                    # Logic's end anchor is the region's length
                ours = [block_fields(b) for b in identity_anchors(frames, spt)]
                self.assertEqual(start, ours[0], key)
                self.assertEqual(end[:3], ours[1][:3], key)
                self.assertLessEqual(abs(end[3] - ours[1][3]), tolerance, key)
                found += 1
            self.assertGreater(found, 0, key)


if __name__ == "__main__":
    unittest.main()
