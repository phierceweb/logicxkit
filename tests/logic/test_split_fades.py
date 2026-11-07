"""A split of a faded region, held to Logic's own split of the same region and to Logic's re-save of
ours: the parent keeps its fade-in, the piece takes the fade-out, and the selection moves to the
piece. A crossfaded region is refused."""

import tempfile
import unittest
from pathlib import Path

import _goldens
from _cli import count, data, run, written
from _audio import THREE, sound_gap_sound

from logicxkit.logic.services.arrange.tracklist import arrange_run
from logicxkit.logic.services.regions.audio_regions import read_audio_regions
from logicxkit.logic.services.regions.audio_write import REGION_TIME_AT, REGION_UUID_FROM_END
from logicxkit.logic.services.regions.fades import read_fade
from logicxkit.logic.services.regions.region_edit import split_region
from logicxkit.logic.services.regions.region_locate import listed, samples_per_tick_of
from logicxkit.logic.services.regions.regions import ENTRY, song_container
from logicxkit.logic.services.stream.stream import HEADER, project_records

BASE, SPLIT, RESAVE = "regions-c01-faded-base-logic", "regions-c02-faded-split-logic", "regions-c03-faded-split-ours-resave-logic"
BAR_THREE = 46080
UNREAD = {0: {14}, 1: set()}   # Logic sets 0x20 on the parent's entry at +14; its meaning is not measured


def entries(d: bytes, n: int | None) -> dict[int, bytes]:
    records = project_records(d)
    payload = records[song_container(records, arrange_run(records, n)).end].raw[HEADER:]
    return {r.piece: payload[r.at:r.at + ENTRY] for r in read_audio_regions(d, n)}


def records(d: bytes, n: int | None) -> dict[int, bytes]:
    """Each piece's region record with the time and UUID a split mints zeroed."""
    out, raws = {}, project_records(d)
    for r in read_audio_regions(d, n):
        raw = bytearray(raws[r.record].raw)
        raw[HEADER + REGION_TIME_AT:HEADER + REGION_TIME_AT + 8] = bytes(8)
        raw[len(raw) - REGION_UUID_FROM_END:len(raw) - REGION_UUID_FROM_END + 16] = bytes(16)
        out[r.piece] = bytes(raw)
    return out


@_goldens.needs(BASE, SPLIT, RESAVE)
class FadedSplitTest(unittest.TestCase):
    def setUp(self):
        before, self.n = data(BASE), count(BASE)
        loc = next(x for x in listed(before, self.n) if x.audio)
        self.ours = split_region(before, loc.number, BAR_THREE, spt=samples_per_tick_of(before, 44100), track_count=self.n)

    def test_the_manifest_facts_are_the_files(self):
        for key, want in ((BASE, [_goldens.fact(BASE, "fade")]), (SPLIT, [p["fade"] for p in _goldens.fact(SPLIT, "pieces")])):
            got = [read_fade(e) for _p, e in sorted(entries(data(key), count(key)).items())]
            self.assertEqual([{k: getattr(f, k) for k in w} for f, w in zip(got, want, strict=True)], want, key)

    def test_each_entry_is_logics_byte_for_byte(self):
        ours, logic = entries(self.ours, self.n), entries(data(SPLIT), count(SPLIT))
        self.assertEqual(sorted(ours), [0, 1])
        for piece in (0, 1):
            with self.subTest(piece=piece):
                diff = [(i, ours[piece][i], logic[piece][i]) for i in range(ENTRY) if ours[piece][i] != logic[piece][i] and i not in UNREAD[piece]]
                self.assertEqual(diff, [])

    def test_each_region_record_is_logics_but_for_the_time_and_uuid_it_mints(self):
        self.assertEqual(records(self.ours, self.n), records(data(SPLIT), count(SPLIT)))

    def test_logic_resaves_our_entries_unchanged(self):
        self.assertEqual(entries(self.ours, self.n), entries(data(RESAVE), count(RESAVE)))


@_goldens.needs(THREE)
class PieceFadeTypeTest(unittest.TestCase):
    def test_the_piece_keeps_the_parents_fade_out_type(self):
        """`split_fades` on bare entries: a parent with a fade-out of type xs (+67 = 5) and no crossfade
        gives the piece the length and curve with the type, and a parent crossfaded at its start keeps
        its own +66..+68 while the piece gets the type alone."""
        from logicxkit.logic.services.regions.fades import CROSSFADE_AT, OUT_TYPE_AT, split_fades
        parent = bytearray(80)
        parent[OUT_TYPE_AT], parent[72], parent[73] = 5, 32, 3
        p, q = split_fades(bytes(parent), bytes(parent))           # the piece starts as a copy, as `_piece_entry` makes it
        self.assertEqual((q[OUT_TYPE_AT], q[72], q[73], p[72], p[73]), (5, 32, 3, 0, 0))
        crossed = bytearray(parent)
        crossed[66], crossed[68] = 0x80, 7
        p, q = split_fades(bytes(crossed), bytes(crossed))
        self.assertEqual((bytes(p[CROSSFADE_AT]), bytes(q[CROSSFADE_AT])), (bytes([0x80, 5, 7]), bytes([0, 5, 0])))


class CrossfadedSplitTest(unittest.TestCase):
    def test_a_region_crossfaded_at_its_end_is_refused_and_nothing_written(self):
        """`--crossfade 1=500` makes "take" the out side of the crossfade into "later": Logic's split of
        that side is unmeasured (the measured one, `regions-c04-crossfade-split-logic`, is the in side)."""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            pair = written(self, "regions", THREE, "--audio", f"Audio 1:1:{sound_gap_sound(out / 'take.wav')}",
                           "--audio", f"Audio 1:3:{sound_gap_sound(out / 'later.wav', gap=0.5)}", out=out / "pair")
            crossed = written(self, "regions", pair, "--crossfade", "1=500", out=out / "crossed")
            code, text = run("regions", crossed, "--split", "1=2", "--out", out / "split")
            self.assertEqual(code, 1, text)
            self.assertIn("crossfaded at its end is not split", text)
            self.assertFalse((out / "split" / crossed.name).exists())

if __name__ == "__main__":
    unittest.main()
