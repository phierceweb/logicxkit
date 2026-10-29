"""Fixtures for the region-edit goldens: the `regions-a*` key table, the facts and song-container
entries two projects are compared by, the listing number of a region by name, and the `Like` case
that holds ours to Logic's save."""

import importlib.util
import struct
import unittest
from pathlib import Path

import _goldens
from logicxkit.logic.services.regions.audio_regions import FILE_TAG, REGION_COUNT_AT, file_name, magic_at
from logicxkit.logic.services.stream.stream import HEADER, project_records
from logicxkit.logic.services.stream.integrity import regressions
from logicxkit.logic.services.regions.region_locate import listed
from logicxkit.logic.services.regions.regions import ENTRY, entry_offsets, song_container
from logicxkit.logic.services.arrange.tracklist import arrange_run
from logicxkit.logic.services.stream.validate import validate_project
from logicxkit.logicx import project_data

_spec = importlib.util.spec_from_file_location("goldens_audio_write", Path(__file__).parent / "goldens" / "test_audio_write.py")
_audio_write = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_audio_write)
LikeLogic, tone = _audio_write.LikeLogic, _audio_write.tone
_spec = importlib.util.spec_from_file_location("goldens_midi_edit", Path(__file__).parent / "goldens" / "test_midi_edit.py")
_midi_edit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_midi_edit)
aliased = _midi_edit.aliased

BAR, BEAT, RATE = 3840, 960, 44100
A = {k: f"regions-a{k:02d}-{name}-logic" for k, name in (
    (0, "base"), (1, "audio-moved"), (2, "audio-start-trimmed"), (3, "audio-end-trimmed"), (4, "audio-split"),
    (5, "audio-muted"), (6, "audio-renamed"), (7, "midi-moved"), (8, "midi-end-trimmed"), (9, "midi-start-trimmed"),
    (10, "midi-split"), (11, "midi-loop-on"), (12, "midi-loop-off"), (13, "audio-loop-on"), (14, "audio-loop-off"),
    (15, "fade-in-500"), (16, "fade-in-curve-50"), (17, "fade-out-500"), (18, "fade-in-speed-up"), (19, "fade-out-curve-30"),
    (20, "crossfade"), (25, "marker-deleted".replace("marker-deleted", "import-e-acute")), (26, "import-e-acute"),
    (28, "import-kanji"), (29, "rename-emoji"), (30, "midi-rename"))}
A[25] = "markers-a25-deleted-logic"


def load(k: int) -> bytes:
    return project_data(_goldens.path(A[k]))


def facts(data: bytes) -> list[tuple]:
    out = []
    for loc in listed(data):
        r = loc.region
        row = (loc.kind, r.track, r.name, r.start, r.loop, r.muted)
        if loc.audio:
            row += (r.frames, r.offset, r.piece, r.file.name if r.file else None, r.fade)
        else:
            row += (tuple((e.tick, e.pitch, e.velocity, e.length) for e in r.events),)
        out.append(row)
    return out


def entries(data: bytes, slots: bool = True) -> list[bytes]:
    """The song container's entries, the edited and selected marks cleared, sorted; ``slots``
    False blanks the sequence slots (Logic's free-slot choice is not ours)."""
    records = project_records(data)
    p = records[song_container(records, arrange_run(records, None)).end].raw[HEADER:]
    out = []
    for off in entry_offsets(p):
        e = bytearray(p[off:off + ENTRY])
        e[13] &= ~0x01
        e[15] = 0
        if not slots:
            e[32:36] = bytes(4)
        out.append(bytes(e))
    return sorted(out)


def region_counts(data: bytes) -> dict[str, int]:
    """Each file record's region count, the word Logic loads that many regions by."""
    out = {}
    for r in project_records(data):
        if r.tag == FILE_TAG:
            p = r.raw[HEADER:]
            out[file_name(p)] = struct.unpack_from("<I", p, magic_at(p) + REGION_COUNT_AT)[0]
    return out


def number(data: bytes, name: str, kind: str = "audio", which: int = 0) -> int:
    return [loc.number for loc in listed(data) if loc.kind == kind and loc.region.name == name][which]


class Like(unittest.TestCase):
    def like(self, ours: bytes, logic: bytes, before: bytes, moved=(), slots: bool = True):
        self.assertEqual(validate_project(ours), [])
        self.assertEqual(regressions(before, ours, removed=moved), [])
        self.assertEqual(facts(ours), facts(logic))
        self.assertEqual(entries(ours, slots), entries(logic, slots))
