"""A split on a project whose registry holds no kind-0x1e run: the pair the blank-born
measurements extended is optional — Logic's own splits of a recorded project added none."""

import unittest

import _goldens
from _cli import count, data

from logicxkit.logic.services.regions.audio_regions import read_audio_regions
from logicxkit.logic.services.regions.region_edit import SPLIT_KIND, split_region
from logicxkit.logic.services.regions.region_locate import listed, samples_per_tick_of
from logicxkit.logic.services.stream.recbuild import rec
from logicxkit.logic.services.stream.registry import GNOS_TAG, SLOT_TYPE, TIME_STRIDE, UUID_STRIDE, run_entries
from logicxkit.logic.services.stream.stream import HEADER, project_records, reassemble
from logicxkit.logic.services.stream.validate import require_valid

BASE = "regions-a00-base-logic"          # region 1 is MIDI; 2, 3 and 4 are audio


def without_split_pairs(project: bytes) -> bytes:
    """``project`` with every kind-0x1e entry cut out of both registry runs."""
    records = project_records(project)
    out = []
    for r in records:
        if r.tag != GNOS_TAG:
            out.append(r.raw)
            continue
        g = bytearray(r.raw[HEADER:])
        for stride in (UUID_STRIDE, TIME_STRIDE):
            for at, _id in reversed(run_entries(g, SPLIT_KIND, stride)):
                del g[at:at + stride]
        out.append(rec(GNOS_TAG, r.raw, bytes(g)))
    return reassemble(project, out)


@_goldens.needs(BASE)
class SplitWithoutRegistryRunTest(unittest.TestCase):
    def test_the_split_goes_through_and_writes_no_pair(self):
        base = without_split_pairs(data(BASE))
        g = next(r.raw[HEADER:] for r in project_records(base) if r.tag == GNOS_TAG)
        self.assertEqual(run_entries(g, SPLIT_KIND, UUID_STRIDE), [])
        n = count(BASE)
        before = read_audio_regions(base, n)
        loc = next(x for x in listed(base, n) if x.audio)
        region = loc.audio
        spt = samples_per_tick_of(base, 44100)
        after = split_region(base, loc.number, region.start + round(region.frames / 2 / spt), spt=spt, track_count=n)
        require_valid(after)
        self.assertEqual(len(read_audio_regions(after, n)), len(before) + 1)
        g_after = next(r.raw[HEADER:] for r in project_records(after) if r.tag == GNOS_TAG)
        for stride in (UUID_STRIDE, TIME_STRIDE):
            self.assertEqual(run_entries(g_after, SPLIT_KIND, stride), [])
            self.assertEqual(len(run_entries(g_after, SLOT_TYPE, stride)), len(run_entries(g, SLOT_TYPE, stride)) + 1)   # the slot pair alone


if __name__ == "__main__":
    unittest.main()
