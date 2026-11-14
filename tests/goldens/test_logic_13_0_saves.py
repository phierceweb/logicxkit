"""Logic 13.0 saves made on copies of 13.0 saves (2026-11-12): the undo stack is loaded, kept and grown
— a no-edit Save As writes the step and `ktSU` back unchanged, each edit appends a step named as the
Undo menu names it and `ktSU` holds the count twice; an add writes the four selection marks on the new
row as 12.x did and leaves the previous row's `+43` mark; an import whose file is found writes the
present byte 1 under 2514; a copy this tool writes carries the stack unchanged; this tool's split of the
imported region equals Logic 13.0's own but for
the region records' time word and UUID, and Logic's re-save of that split keeps every row but a byte on the second
piece and the selected row's `+43` mark."""

import contextlib
import io
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _goldens

from logicxkit.cli import main as logicxkit_main
from logicxkit.logic.services.arrange.environment import ENV_TAG, object_id_of
from logicxkit.logic.services.arrange.environment import SELECTED_AT as OBJECT_SELECTED_AT
from logicxkit.logic.services.arrange.stacks import read_tracks
from logicxkit.logic.services.arrange.tracklist import EXPANDED_AT, SELECTED_AT, SELECTED_BIT, SELECTED_MARK, arrange_run, row_object
from logicxkit.logic.services.regions.audio_regions import FILE_TAG, PATH_AT, REGION_TAG, file_present, magic_at, read_audio_files, read_audio_regions
from logicxkit.logic.services.regions.audio_write import REGION_UUID_FROM_END
from logicxkit.logic.services.stream.registry import GNOS_TAG, SELECTED_OBJECT_AT, SELECTED_TRACK2_AT, SELECTED_TRACK_AT
from logicxkit.logic.services.stream.stream import HEADER, project_records
from logicxkit.logic.services.stream.validate import file_format
from logicxkit.logicx import project_data

UNDO_RESAVE, UNDO_ADD = "undo-a01-resave-13-0-logic", "undo-a02-create-track-13-0-logic"
IMPORT, SPLIT, ADD = "regions-d01-import-13-0-logic", "regions-d02-split-13-0-logic", "regions-d03-add-track-13-0-logic"
RESAVED = "regions-d04-split-ours-resave-13-0-logic"
KEYS = (UNDO_RESAVE, UNDO_ADD, IMPORT, SPLIT, ADD, RESAVED)
CHURN = {b"gnoS", b"qeSM", b"qSvE", b"lESU"}
REGION_SAVED_AT, ROW_MARK_AT = 136, 43                    # the piece number a 13.0 save stamps; the mark one clears
TIME_AT = (42, 50)                                # a region record's time word, fresh on every Logic save, as is its UUID
PATH_LEN = 256


def records(key):
    return project_records(project_data(_goldens.path(key)))


def undo_steps(recs) -> list[str]:
    return [r.raw[HEADER + 8:HEADER + 8 + struct.unpack_from("<I", r.raw, HEADER)[0]].decode() for r in recs if r.tag == b"lESU"]


def region_facts(data, count) -> list[tuple]:
    return [(r.name, r.start, r.frames, r.piece, r.offset, r.track) for r in read_audio_regions(data, count)]


def our_split(tmp: str) -> bytes:
    """`regions --split 1=3` on the 13.0 import, the format gate opened for the run."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out), mock.patch("logicxkit.logic.cli.formats", lambda cmd: (2513, 2514)):
        code = logicxkit_main(["logic", "regions", str(_goldens.path(IMPORT)), "--split", "1=3", "--out", tmp])
    if code != 0:
        raise AssertionError(out.getvalue())
    return project_data(next(Path(tmp).glob("*.logicx")))


def masked(payload: bytes, spans) -> bytes:
    out = bytearray(payload)
    for start, stop in spans:
        out[start:stop] = bytes(stop - start)
    return bytes(out)


def stamps(region: bytes) -> tuple[tuple[int, int], ...]:
    """The time word and the UUID (16 bytes, 47 before the end, so it moves with the name's length)."""
    return TIME_AT, (len(region) - REGION_UUID_FROM_END, len(region) - REGION_UUID_FROM_END + 16)


@_goldens.needs(*KEYS)
class UndoStackTest(unittest.TestCase):
    def test_the_stack_is_kept_and_grown_one_step_per_edit(self):
        for key in KEYS:
            with self.subTest(key=key):
                recs = records(key)
                steps = _goldens.fact(key, "undo_steps")
                self.assertEqual(undo_steps(recs), steps)
                self.assertEqual([r.raw[HEADER:] for r in recs if r.tag == b"ktSU"], [struct.pack("<II", len(steps), len(steps))])
                self.assertEqual(file_format(project_data(_goldens.path(key))), 2514)

    def test_our_copy_carries_the_saved_undo_stack_unchanged(self):
        """A 2514 copy this tool writes keeps the input's undo stack as the input holds it — `ktSU` and every
        `lESU` byte for byte — as Logic's own re-save of that copy carried it on (`regions-d04-split-ours-resave-13-0-logic`)."""
        stack = lambda recs: [r.raw for r in recs if r.tag in (b"ktSU", b"lESU")]      # noqa: E731
        with tempfile.TemporaryDirectory() as tmp:
            ours = project_records(our_split(tmp))
        self.assertEqual(stack(ours), stack(records(IMPORT)))
        self.assertEqual(undo_steps(ours), _goldens.fact(IMPORT, "undo_steps"))
        self.assertEqual(undo_steps(ours), undo_steps(records(RESAVED)))


@_goldens.needs(UNDO_ADD, ADD)
class SelectionUnderLogic13Test(unittest.TestCase):
    def marks(self, key):
        data = project_data(_goldens.path(key))
        recs = project_records(data)
        count = _goldens.fact(key, "tracks")
        by_name = {t["name"]: t["object_id"] for t in read_tracks(data, count)}
        run = arrange_run(recs, count)
        flagged = [row_object(recs[i].raw) for i in run if recs[i].raw[HEADER + EXPANDED_AT] & SELECTED_BIT]
        marked = [row_object(recs[i].raw) for i in run if recs[i].raw[HEADER + SELECTED_AT] & SELECTED_MARK]
        objects = [object_id_of(r) for r in recs if r.tag == ENV_TAG and len(r.raw) > HEADER + OBJECT_SELECTED_AT and r.raw[HEADER + OBJECT_SELECTED_AT] == 1]
        song = next(r.raw[HEADER:] for r in recs if r.tag == GNOS_TAG)
        registry = (struct.unpack_from("<I", song, SELECTED_OBJECT_AT)[0], struct.unpack_from("<H", song, SELECTED_TRACK_AT)[0],
                    struct.unpack_from("<I", song, SELECTED_TRACK2_AT)[0])
        return by_name, flagged, marked, objects, registry

    def test_an_add_writes_the_four_marks_on_the_new_row(self):
        for key in (UNDO_ADD, ADD):
            with self.subTest(key=key):
                by_name, flagged, marked, objects, registry = self.marks(key)
                new = by_name[_goldens.fact(key, "added")]
                self.assertEqual(_goldens.fact(key, "selected"), _goldens.fact(key, "added"))
                self.assertEqual(flagged, [new])
                self.assertIn(new, marked)
                self.assertEqual(objects, [new])
                row = _goldens.fact(key, "selected_row")
                self.assertEqual(registry, (new, row, row))

    def test_the_previous_rows_mark_stays_where_an_edit_set_it(self):
        """The import marked Audio 1's row; the add moved the selection and left that mark (12.x's
        `select_rows` clears it). On the reset save no row was marked before the add."""
        by_name, _f, marked, _o, _r = self.marks(ADD)
        self.assertEqual(sorted(marked), sorted([by_name["Audio 1"], by_name["Audio 3"]]))
        by_name, _f, marked, _o, _r = self.marks(UNDO_ADD)
        self.assertEqual(marked, [by_name["Audio 3"]])


@_goldens.needs(IMPORT, SPLIT, ADD)
class AudioUnderLogic13Test(unittest.TestCase):
    def test_a_found_file_reads_present_with_the_13_0_leading_word(self):
        data = project_data(_goldens.path(IMPORT))
        files = [r.raw[HEADER:] for r in project_records(data) if r.tag == FILE_TAG]
        self.assertEqual(len(files), 1)
        self.assertEqual((file_present(files[0]), struct.unpack_from("<I", files[0], 4)[0]), (_goldens.fact(IMPORT, "present"), 952))
        f = read_audio_files(data)[0]
        self.assertEqual((f.name, f.frames, f.rate, f.channels, f.bits),
                         tuple(_goldens.fact(IMPORT, k) for k in ("file", "frames", "rate", "channels", "bits")))

    def test_the_regions_read_as_logic_shows_them(self):
        for key in (IMPORT, SPLIT, ADD):
            with self.subTest(key=key):
                data = project_data(_goldens.path(key))
                want = [(r["name"], r["start"], r["frames"], r["piece"], r.get("offset", 0), r["track"]) for r in _goldens.fact(key, "regions")]
                self.assertEqual(region_facts(data, _goldens.fact(key, "tracks")), want)

    def test_our_split_equals_logics_but_for_the_stamps(self):
        """`regions --split` on the 13.0 import, the format gate opened for the run, against Logic
        13.0's own split of the same project: the same regions, the same region and file records but
        for the UUID and time words and the file record's path buffer."""
        with tempfile.TemporaryDirectory() as tmp:
            ours = our_split(tmp)
        logic = project_data(_goldens.path(SPLIT))
        count = _goldens.fact(SPLIT, "tracks")
        self.assertEqual(region_facts(ours, count), region_facts(logic, count))
        ours_regions = [r.raw[HEADER:] for r in project_records(ours) if r.tag == REGION_TAG]
        logic_regions = [r.raw[HEADER:] for r in project_records(logic) if r.tag == REGION_TAG]
        self.assertEqual(len(ours_regions), 2)
        self.assertEqual([masked(p, stamps(p)) for p in ours_regions], [masked(p, stamps(p)) for p in logic_regions])
        self.assertNotEqual(ours_regions, logic_regions)
        ours_file = next(r.raw[HEADER:] for r in project_records(ours) if r.tag == FILE_TAG)
        logic_file = next(r.raw[HEADER:] for r in project_records(logic) if r.tag == FILE_TAG)
        path = magic_at(ours_file) + PATH_AT
        self.assertEqual(masked(ours_file, ((path, path + PATH_LEN),)), masked(logic_file, ((path, path + PATH_LEN),)))

    def test_logics_re_save_of_our_split_keeps_every_row(self):
        """Logic 13.0 opened our 2514 split and saved it with no change (`regions-d04-split-ours-resave-13-0-logic`):
        every record as written but the song record, the sequence records and the carried undo step (rewritten
        on every save), the file record's path buffer, `+136` of the second piece set to 1 and the selected
        row's `+43` mark cleared."""
        with tempfile.TemporaryDirectory() as tmp:
            ours = project_records(our_split(tmp))
        theirs = project_records(project_data(_goldens.path(RESAVED)))
        identity = lambda r: (r.tag, None if r.tag in CHURN else r.owner, r.key)      # noqa: E731  a sequence's owner moves on every save
        self.assertEqual([identity(r) for r in ours], [identity(r) for r in theirs])
        changed = {}
        for a, b in zip(ours, theirs, strict=True):
            if a.tag in CHURN or a.raw == b.raw:
                continue
            self.assertEqual(len(a.raw), len(b.raw), a.tag)
            x, y = a.raw[HEADER:], b.raw[HEADER:]
            if a.tag == FILE_TAG:
                path = magic_at(x) + PATH_AT
                x, y = masked(x, ((path, path + PATH_LEN),)), masked(y, ((path, path + PATH_LEN),))
            if a.tag == REGION_TAG:
                x, y = masked(x, stamps(x)), masked(y, stamps(y))       # this run's stamps against the staged run's
            diff = [(i, x[i], y[i]) for i in range(len(x)) if x[i] != y[i]]
            if diff:
                changed[(a.tag, a.owner)] = diff
        self.assertEqual(changed, {(REGION_TAG, 1): [(REGION_SAVED_AT, 0, 1)], (b"karT", 65535): [(ROW_MARK_AT, 0x4C, 0x0C)]})

if __name__ == "__main__":
    unittest.main()
