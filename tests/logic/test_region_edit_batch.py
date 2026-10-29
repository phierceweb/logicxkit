"""Region edits in a batch: each writer can skip its own validation so a run of them is validated
once, and the result is what the validated edits give."""

import unittest

import _goldens
from _cli import count, data

from logicxkit.logic.services.regions.audio_regions import read_audio_regions
from logicxkit.logic.services.regions.fades import Fade
from logicxkit.logic.services.regions.region_edit import rename_region, set_fade, split_region, trim_region
from logicxkit.logic.services.regions.region_locate import listed, samples_per_tick_of
from logicxkit.logic.services.stream.validate import require_valid

BASE = "regions-a00-base-logic"          # region 1 is MIDI; 2, 3 and 4 are audio


def summary(project: bytes, n: int | None) -> list[tuple]:
    return sorted((r.track, r.name, r.start, r.offset, r.frames, r.fade) for r in read_audio_regions(project, n))


@_goldens.needs(BASE)
class BatchedEditsTest(unittest.TestCase):
    def test_unvalidated_edits_land_as_the_validated_ones_do(self):
        base, n = data(BASE), count(BASE)
        spt = samples_per_tick_of(base, 44100)
        loc = next(x for x in listed(base, n) if x.audio)
        cut = loc.audio.start + round(loc.audio.frames / 2 / spt)
        checked = split_region(base, loc.number, cut, spt=spt, track_count=n)
        checked = rename_region(checked, loc.number + 1, "piece", n)
        checked = trim_region(checked, loc.number + 1, start=cut + 100, spt=spt, track_count=n)
        checked = set_fade(checked, loc.number, Fade(out_ms=20), n)
        batched = split_region(base, loc.number, cut, spt=spt, track_count=n, validate=False)
        batched = rename_region(batched, loc.number + 1, "piece", n, validate=False)
        batched = trim_region(batched, loc.number + 1, start=cut + 100, spt=spt, track_count=n, validate=False)
        batched = set_fade(batched, loc.number, Fade(out_ms=20), n, validate=False)
        require_valid(batched)
        self.assertEqual(summary(batched, n), summary(checked, n))
        self.assertEqual(len(summary(batched, n)), 4)


if __name__ == "__main__":
    unittest.main()
