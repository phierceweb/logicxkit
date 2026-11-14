"""Logic 13.0's own region edits chained on the 13.0 split save (2026-11-12, `regions-d05`..`d12`: move, halve,
start to previous region, loop, mute, rename, fade in, fade out), this tool's writes on 13.0 inputs (`d13`, `d15`,
`d17`, `d19`: the same edits, the MIDI edits, the parameters, an import) and Logic 13.0's no-change re-save of each
(`d14`, `d16`, `d18`, `d20`). Logic's edits leave bookkeeping ours never writes — a touched record's piece number
at `+136`, the cut-off tail of a length change as an unreferenced record, tail words, "current" bytes, two tick
words in the track's object — and its re-save of each write keeps every record but that piece number and the
row mark; the import's re-save rewrites the file record for Logic's own copy of the WAV and flags the row."""

import contextlib
import difflib
import io
import struct
import tempfile
import unittest
import wave
from collections import Counter
from pathlib import Path
from unittest import mock

import _goldens
from _region_edit import entries, facts
from goldens.test_logic_13_0_saves import CHURN, masked, stamps, undo_steps

from logicxkit.cli import main as logicxkit_main
from logicxkit.logic.services.arrange.environment import ENV_TAG
from logicxkit.logic.services.arrange.tracklist import CONTENT_FLAG, CONTENT_MARK, arrange_run, row_object
from logicxkit.logic.services.regions.audio_regions import FILE_TAG, PATH_AT, REGION_COUNT_AT, REGION_FRAMES_AT, REGION_OFFSET_AT, REGION_TAG, magic_at, piece_number_at
from logicxkit.logic.services.regions.audio_write import FILE_CURRENT_AT, REGION_CURRENT_AT
from logicxkit.logic.services.regions.region_locate import listed
from logicxkit.logic.services.stream.stream import HEADER, project_records
from logicxkit.logic.services.stream.validate import file_format, validate_project
from logicxkit.logicx import project_data

SPLIT, IMPORT, BLANK = "regions-d02-split-13-0-logic", "regions-d01-import-13-0-logic", "tracks-two-audio-13-0-logic"
ADD_TRACK = "regions-d03-add-track-13-0-logic"
MOVE, HALVE, START, LOOP, MUTE, RENAME, FADE_IN, FADE_OUT = CHAIN = tuple(
    f"regions-d{n:02d}-{what}-13-0-logic" for n, what in enumerate(("move", "halve", "start-to-previous", "loop", "mute", "rename", "fade-in", "fade-out"), 5))
OURS = {"edits": ("regions-d13-edits-ours-13-0", "regions-d14-edits-ours-resave-13-0-logic"),
        "midi": ("regions-d15-midi-ours-13-0", "regions-d16-midi-ours-resave-13-0-logic"),
        "params": ("regions-d17-params-ours-13-0", "regions-d18-params-ours-resave-13-0-logic"),
        "import": ("regions-d19-import-ours-13-0", "regions-d20-import-ours-resave-13-0-logic")}
EDITS = ["--move", "2=4", "--trim", "2=:1", "--trim", "2=3:", "--loop", "2", "--mute", "1", "--rename", "1=tone renamed", "--fade-in", "1=500", "--fade-out", "1=500"]
PIECE_AT_12, TAIL_FROM_END, SHIFT_FROM_END, ROW_MARK_AT, ROW_FLAGS_AT = 136, 11, 15, 43, 2     # the piece number sits 48 past the name: +136 for the d-series' 12-byte names
ARCHIVE_STAMP = 16                        # a keyed archive's trailing bytes, fresh on every 13.0 save
PATH_LEN = 256
ARRANGE_ROW, ARRANGE_ROW_2 = (b"karT", 65535, 0, 1), (b"karT", 65535, 1, 0)     # the arrange run's first two rows (a run marker shares key 0)
LEADING = (920, 952)                      # the file record's +4 under Logic 12 and 13.0


def data(key: str) -> bytes:
    return project_data(_goldens.path(key))


def records(key: str):
    return [r for r in project_records(data(key)) if r.tag not in CHURN]


def regions(key: str):
    return [r.raw[HEADER:] for r in project_records(data(key)) if r.tag == REGION_TAG]


def rows(d: bytes) -> list[dict]:
    """The regions as the manifest records them."""
    out = []
    for loc in listed(d):
        r = loc.region
        row = {"kind": loc.kind, "track": r.track, "name": r.name, "start": r.start, "loop": r.loop, "muted": r.muted}
        if loc.audio:
            f = r.fade
            row.update(frames=r.frames, offset=r.offset, piece=r.piece, file=r.file.name if r.file else None,
                       fade=[f.in_ms, f.in_curve, f.in_type, f.out_ms, f.out_curve, f.out_type])
        else:
            row["events"] = [[e.tick, e.pitch, e.velocity, e.length] for e in r.events]
        out.append(row)
    return out


def our_edits(tmp: str) -> bytes:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), mock.patch("logicxkit.logic.cli.formats", lambda cmd: (2513, 2514)):
        code = logicxkit_main(["logic", "regions", str(_goldens.path(SPLIT)), *EDITS, "--out", tmp])
    if code != 0:
        raise AssertionError(out.getvalue())
    return project_data(next(Path(tmp).glob("*.logicx")))


def our_import(tmp: str) -> bytes:
    """`regions --audio` of a tone shaped like the one Logic imported (eight seconds, 44.1 kHz, mono, 16-bit) onto
    Audio 1 of the 13.0 twin of the blank, the format gate opened for the run."""
    wav = Path(tmp, "v0170-tone.wav")
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(bytes(2 * _goldens.fact(IMPORT, "frames")))
    out = io.StringIO()
    with contextlib.redirect_stdout(out), mock.patch("logicxkit.logic.cli.formats", lambda cmd: (2513, 2514)):
        code = logicxkit_main(["logic", "regions", str(_goldens.path(BLANK)), "--audio", f"Audio 1:1:{wav}", "--out", str(Path(tmp, "out"))])
    if code != 0:
        raise AssertionError(out.getvalue())
    return project_data(next(Path(tmp, "out").glob("*.logicx")))


def spans(tag: bytes, payload: bytes):
    """The bytes a comparison masks: a file record's path buffer, a region's time word and UUID, an archive's stamp."""
    if tag == FILE_TAG:
        at = magic_at(payload) + PATH_AT
        return ((at, at + PATH_LEN),)
    if tag == REGION_TAG:
        return stamps(payload)
    if tag == b"UCuA":
        return ((len(payload) - ARCHIVE_STAMP, len(payload)),)
    return ()


LINE = 16                      # a sequence record is 16-byte lines
REORDERED, UNPAIRED = "reordered", "unpaired"


def sequence_differences(ours: str, logic: str, tag: bytes = b"qSvE") -> list[tuple[int, object]]:
    """`payload_differences` of two staged saves, by manifest key."""
    return payload_differences(data(ours), data(logic), tag)


def payload_differences(ours: bytes, logic: bytes, tag: bytes = b"qSvE") -> list[tuple[int, object]]:
    """The `qSvE` sequence records (events, marker lists, the tempo and signature maps) `compared` drops as churn, set
    against each other as payload multisets. Each payload only one side holds is paired once with the nearest same-length
    payload only the other side holds: `(length, REORDERED)` when the two hold the same 16-byte lines in another order,
    `(length, offsets)` for the bytes that differ otherwise, `(length, UNPAIRED)` for a payload with no partner."""
    mine, theirs = (Counter(r.raw[HEADER:] for r in project_records(d) if r.tag == tag) for d in (ours, logic))
    pool, out = list((theirs - mine).elements()), []
    for p in (mine - theirs).elements():
        partners = [q for q in pool if len(q) == len(p)]
        if not partners:
            out.append((len(p), UNPAIRED))
            continue
        q = max(partners, key=lambda q: sum(x == y for x, y in zip(p, q, strict=True)))
        pool.remove(q)
        lines = lambda s: Counter(s[i:i + LINE] for i in range(0, len(s), LINE))        # noqa: E731
        out.append((len(p), REORDERED if lines(p) == lines(q) else tuple(i for i in range(len(p)) if p[i] != q[i])))
    out += [(len(q), UNPAIRED) for q in pool]
    return sorted(out, key=str)


def compared(a, b) -> tuple[list, list, dict]:
    """Records paired by (tag, owner, key) outside the churn: the unpaired of each side, and for every pair that
    differs outside the masked spans, its (tag, owner, key, n) -> the offsets that differ."""
    ida, idb = [(r.tag, r.owner, r.key) for r in a], [(r.tag, r.owner, r.key) for r in b]
    only_a, only_b, pairs = [], [], []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, ida, idb, autojunk=False).get_opcodes():
        if op == "equal":
            pairs += list(zip(a[i1:i2], b[j1:j2], strict=True))
        else:
            only_a += a[i1:i2]
            only_b += b[j1:j2]
    changed, seen = {}, {}
    for x, y in pairs:
        n = seen[(x.tag, x.owner, x.key)] = seen.get((x.tag, x.owner, x.key), -1) + 1
        p, q = x.raw[HEADER:], y.raw[HEADER:]
        if len(p) != len(q):
            changed[(x.tag, x.owner, x.key, n)] = ("length", len(p), len(q))
            continue
        p, q = masked(p, spans(x.tag, p)), masked(q, spans(y.tag, q))
        diff = tuple(i for i in range(len(p)) if p[i] != q[i])
        if diff:
            changed[(x.tag, x.owner, x.key, n)] = diff
    return only_a, only_b, changed


def piece_record(p: bytes) -> tuple[int, int]:
    return struct.unpack_from("<I", p, REGION_OFFSET_AT)[0], struct.unpack_from("<I", p, REGION_FRAMES_AT)[0]


@_goldens.needs(SPLIT, *CHAIN)
class LogicsChainTest(unittest.TestCase):
    def test_each_save_reads_as_logic_showed_it(self):
        for key in CHAIN:
            with self.subTest(key=key):
                d = data(key)
                self.assertEqual(file_format(d), 2514)
                self.assertEqual(rows(d), _goldens.fact(key, "regions"))
                self.assertEqual(undo_steps(project_records(d)), _goldens.fact(key, "undo_steps"))
                self.assertEqual(validate_project(d), [])

    def test_a_touched_record_carries_its_piece_number_past_its_name(self):
        """0 on the split's fresh piece; the header owner once a 13.0 save has touched the record — 13.0's home of
        what 12.x kept at +130, 48 bytes past the padded name (`+136` on these 12-byte names)."""
        self.assertEqual([(p[piece_number_at(p)], struct.unpack_from("<H", p, 130)[0]) for p in regions(SPLIT)], [(0, 0), (0, 0)])
        self.assertEqual([piece_number_at(p) for p in regions(SPLIT)], [PIECE_AT_12 - 2, PIECE_AT_12])     # 'v0170-tone', 'v0170-tone.1'
        for key in CHAIN:
            recs = [r for r in project_records(data(key)) if r.tag == REGION_TAG]
            self.assertEqual([r.raw[HEADER + piece_number_at(r.raw[HEADER:])] for r in recs], [r.owner for r in recs], key)
            self.assertEqual([struct.unpack_from("<H", r.raw, HEADER + 130)[0] for r in recs], [0] * len(recs), key)

    def test_the_halve_keeps_the_cut_tail_as_a_record_no_entry_points_at(self):
        self.assertEqual([piece_record(p) for p in regions(MOVE)], [(0, 176400), (176400, 176400)])
        self.assertEqual([piece_record(p) for p in regions(HALVE)], [(0, 176400), (176400, 88200), (264600, 88200)])
        self.assertEqual(len(_goldens.fact(HALVE, "regions")), 2)
        for key, count in ((MOVE, 2), (HALVE, 3), (FADE_OUT, 3)):
            f = next(r.raw[HEADER:] for r in project_records(data(key)) if r.tag == FILE_TAG)
            self.assertEqual(struct.unpack_from("<I", f, magic_at(f) + REGION_COUNT_AT)[0], count, key)

    def test_the_start_trim_moves_the_content_in_place_and_writes_the_shift(self):
        """One sample: the piece's start back a bar, its offset down and its length up by that bar's frames, and a
        signed tick word 15 before the record's end reading -3840 (a bar at 960 PPQ)."""
        before, after = regions(HALVE)[1], regions(START)[1]
        self.assertEqual((piece_record(before), piece_record(after)), (((176400, 88200)), (88200, 176400)))
        self.assertEqual(struct.unpack_from("<i", before, len(before) - SHIFT_FROM_END)[0], 0)
        self.assertEqual(struct.unpack_from("<i", after, len(after) - SHIFT_FROM_END)[0], -3840)

    def test_the_tail_word_and_the_current_bytes_as_logic_left_them(self):
        """The u32 11 before a region record's end, and the "current" bytes (region +38, file magic+7), after each
        edit: values only — their meaning is not claimed."""
        tail = lambda key: [struct.unpack_from("<I", p, len(p) - TAIL_FROM_END)[0] for p in regions(key)]        # noqa: E731
        self.assertEqual(tail(SPLIT), [0xFFFFFFFF, 1])
        self.assertEqual(tail(HALVE), [0, 0xFFFFFFFF, 1])
        self.assertEqual(tail(START), [0, 1, 0])
        self.assertEqual(tail(FADE_OUT), [0, 1, 0])
        current = lambda key: [p[REGION_CURRENT_AT] for p in regions(key)]        # noqa: E731
        file_current = lambda key: next(r.raw[HEADER + magic_at(r.raw[HEADER:]) + FILE_CURRENT_AT] for r in project_records(data(key)) if r.tag == FILE_TAG)   # noqa: E731
        self.assertEqual((current(MUTE), file_current(MUTE)), ([1, 1, 1], 1))
        self.assertEqual((current(RENAME), file_current(RENAME)), ([1, 0, 0], 0))


@_goldens.needs(SPLIT, FADE_OUT, IMPORT, OURS["edits"][0], OURS["import"][0])
class OurWritesAgainstLogicsTest(unittest.TestCase):
    def test_our_edits_write_is_the_staged_one_and_reads_as_logics_eighth_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            ours = our_edits(tmp)
        staged, logic = data(OURS["edits"][0]), data(FADE_OUT)
        self.assertEqual(validate_project(ours), [])
        only_ours, only_staged, changed = compared([r for r in project_records(ours) if r.tag not in CHURN], records(OURS["edits"][0]))
        self.assertEqual((only_ours, only_staged, changed), ([], [], {}))
        self.assertEqual((facts(staged), entries(staged)), (facts(logic), entries(logic)))

    def test_logics_own_edits_leave_bookkeeping_ours_never_writes(self):
        """Against Logic's eighth save our write lacks the cut tail's record, and differs in the file record's
        "current" byte and region count, the records' piece numbers, tail and shift words and "current" bytes, two
        tick words of the track's object, the row mark and the undo count — and in nothing else."""
        only_ours, only_logic, changed = compared(records(OURS["edits"][0]), records(FADE_OUT))
        self.assertEqual(only_ours, [])
        self.assertEqual([(r.tag, r.owner, piece_record(r.raw[HEADER:])) for r in only_logic], [(REGION_TAG, 2, (264600, 88200))])
        m = magic_at(next(r.raw[HEADER:] for r in records(FADE_OUT) if r.tag == FILE_TAG))
        self.assertEqual(changed, {
            (FILE_TAG, 65535, 65535, 0): (m + FILE_CURRENT_AT, m + REGION_COUNT_AT),
            (REGION_TAG, 0, 65535, 0): (210, 211, 212, 213),
            (REGION_TAG, 1, 65535, 0): (REGION_CURRENT_AT, PIECE_AT_12, 207, 208, 209),
            (ENV_TAG, 65535, 65535, 1): (279, 327),              # the track's object: two tick words, one bar up
            ARRANGE_ROW: (ROW_MARK_AT,),
            (b"ktSU", 65535, 65535, 0): (0, 4)})

    def test_our_import_differs_from_logics_in_the_file_words_the_row_flags_and_the_selection(self):
        ours, logic = data(OURS["import"][0]), data(IMPORT)
        self.assertEqual((facts(ours), entries(ours)), (facts(logic), entries(logic)))
        only_ours, only_logic, changed = compared(records(OURS["import"][0]), records(IMPORT))
        self.assertEqual((only_ours, only_logic), ([], []))
        m = magic_at(next(r.raw[HEADER:] for r in records(IMPORT) if r.tag == FILE_TAG))
        self.assertEqual(changed, {
            (FILE_TAG, 65535, 65535, 0): (0, 4, m + 406, m + 407, m + 530, m + 531),      # 920/952; Logic's copy of the WAV
            (b"OCuA", 9, 65535, 0): (80,),
            (ENV_TAG, 65535, 65535, 11): (80,), (ENV_TAG, 65535, 65535, 12): (80,),             # the two tracks' objects: the selection moved by the click before the import
            ARRANGE_ROW: (ROW_FLAGS_AT, 40, ROW_MARK_AT), ARRANGE_ROW_2: (40,),
            (b"ktSU", 65535, 65535, 0): (0, 4)})


@_goldens.needs(SPLIT, ADD_TRACK)
class FreshAddTrackTest(unittest.TestCase):
    def test_a_fresh_add_track_keeps_the_content_mark_logics_own_add_keeps(self):
        """Our add beside the split's track against Logic's own (d02 -> d03): every row the two share carries the same
        content flags (`+2`, `+43`'s 0x0c); the selected mark (0x40) is the measured difference, cleared by ours."""
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(out), \
                mock.patch("logicxkit.logic.cli.formats", lambda cmd: (2513, 2514)):
            code = logicxkit_main(["logic", "add-track", str(_goldens.path(SPLIT)), "--name", "Audio 3", "--after", "Audio 1", "--out", tmp])
            self.assertEqual(code, 0, out.getvalue())
            ours = project_data(next(Path(tmp).glob("*.logicx")))
        marks = lambda d: {row_object(r.raw): (r.raw[HEADER + ROW_FLAGS_AT], r.raw[HEADER + ROW_MARK_AT] & CONTENT_MARK)   # noqa: E731
                           for r in (project_records(d)[i] for i in arrange_run(project_records(d), 3))}
        mine, logics = marks(ours), marks(data(ADD_TRACK))
        shared = set(mine) & set(logics)
        self.assertGreaterEqual(len(shared), 2)
        self.assertEqual({o: mine[o] for o in shared}, {o: logics[o] for o in shared})
        self.assertIn((CONTENT_FLAG, CONTENT_MARK), mine.values())                      # the split's track keeps its region's marks


@_goldens.needs(IMPORT, BLANK)
class FreshImportTest(unittest.TestCase):
    def test_an_import_writes_13_0s_file_word_and_the_rows_content_flags(self):
        """What the staged import (`regions-d19`) left to Logic, the writer now writes: against Logic's own import
        the file record differs in the size and chunk words of Logic's copy of the WAV alone, and the row in its
        selection bits alone."""
        with tempfile.TemporaryDirectory() as tmp:
            ours = our_import(tmp)
        logic = data(IMPORT)
        self.assertEqual(validate_project(ours), [])
        self.assertEqual((facts(ours), entries(ours)), (facts(logic), entries(logic)))
        recs = [r for r in project_records(ours) if r.tag not in CHURN]
        only_ours, only_logic, changed = compared(recs, records(IMPORT))
        self.assertEqual((only_ours, only_logic), ([], []))
        m = magic_at(next(r.raw[HEADER:] for r in recs if r.tag == FILE_TAG))
        self.assertEqual(changed, {
            (FILE_TAG, 65535, 65535, 0): (m + 406, m + 407, m + 530, m + 531),
            (b"OCuA", 9, 65535, 0): (80,),
            (ENV_TAG, 65535, 65535, 11): (80,), (ENV_TAG, 65535, 65535, 12): (80,),
            ARRANGE_ROW: (40, ROW_MARK_AT), ARRANGE_ROW_2: (40,),
            (b"ktSU", 65535, 65535, 0): (0, 4)})
        f = next(r.raw[HEADER:] for r in recs if r.tag == FILE_TAG)
        self.assertEqual((struct.unpack_from("<I", f, 0)[0] & 0x3FFFF, struct.unpack_from("<I", f, 4)[0]), (952, 952))
        row = [r.raw[HEADER:] for r in recs if r.tag == b"karT" and r.key == 0][ARRANGE_ROW[3]]
        self.assertEqual((row[ROW_FLAGS_AT], row[ROW_MARK_AT]), (CONTENT_FLAG, CONTENT_MARK))


@_goldens.needs(*(k for pair in OURS.values() for k in pair))
class LogicsReSaveOfOurWritesTest(unittest.TestCase):
    KEPT = {"edits": {(REGION_TAG, 1, 65535, 0): (PIECE_AT_12,), ARRANGE_ROW: (ROW_MARK_AT,)},
            "midi": {},
            "params": {(REGION_TAG, 1, 65535, 0): (PIECE_AT_12,), ARRANGE_ROW: (ROW_MARK_AT,)}}

    def test_logic_kept_every_record_of_the_edits_midi_and_parameter_writes(self):
        for name, expected in self.KEPT.items():
            with self.subTest(name=name):
                ours, logic = OURS[name]
                self.assertEqual(validate_project(data(logic)), [])
                self.assertEqual((facts(data(ours)), entries(data(ours))), (facts(data(logic)), entries(data(logic))))
                only_ours, only_logic, changed = compared(records(ours), records(logic))
                self.assertEqual((only_ours, only_logic, changed), ([], [], expected))

    def test_the_import_re_save_rewrites_the_file_record_for_logics_copy_and_flags_the_row(self):
        """Logic rewrites the imported WAV inside the package to its own form and the file record for it (the 13.0
        leading word, the size, the chunk word), sets the row's content flags (+2 0x14, +43 0x0c) our import never
        set, and stamps its archives; the region records as written."""
        ours, logic = OURS["import"]
        self.assertEqual((facts(data(ours)), entries(data(ours))), (facts(data(logic)), entries(data(logic))))
        only_ours, only_logic, changed = compared(records(ours), records(logic))
        m = magic_at(next(r.raw[HEADER:] for r in records(ours) if r.tag == FILE_TAG))
        self.assertEqual((only_ours, only_logic), ([], []))
        self.assertEqual(changed, {
            (FILE_TAG, 65535, 65535, 0): (0, 4, m + 406, m + 407, m + 530, m + 531),
            (b"OCuA", 9, 65535, 0): (80,),
            ARRANGE_ROW: (ROW_FLAGS_AT, ROW_MARK_AT)})
        leading = [struct.unpack_from("<I", r.raw, HEADER + 4)[0] for key in (ours, logic) for r in records(key) if r.tag == FILE_TAG]
        self.assertEqual(leading, list(LEADING))
        row = [r.raw[HEADER:] for r in records(logic) if r.tag == b"karT" and r.key == 0][ARRANGE_ROW[3]]
        self.assertEqual((row[ROW_FLAGS_AT], row[ROW_MARK_AT]), (0x14, 0x0C))


if __name__ == "__main__":
    unittest.main()
