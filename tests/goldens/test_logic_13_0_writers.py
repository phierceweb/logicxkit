"""The one-write commands on Logic 13.0 inputs (2026-11-12): this tool's write on a public 13.0 twin, the format gate
opened for the run (`<family>-ours-13-0`), and Logic 13.0's no-change Save As of it (`<family>-ours-resave-13-0-logic`),
compared record by record and through each command's own reader. Thirteen families come back as written but for the
bytes every 13.0 re-save rewrites (a channel's `+80`, the row mark) or in nothing; six have Logic completing words the
writer leaves (a new object's 12.x type word, meter-derived tick words, a channel's pan from its lane, row flags, one
row UUID); the four slot families and `width` have Logic re-laying records (`EXPECTED` pins each)."""

import contextlib
import io
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _goldens
from goldens.test_logic_13_0_regions import CHURN, REORDERED, compared, records, sequence_differences
from logic._beats import beat, index

from logicxkit.cli import main as logicxkit_main
from logicxkit.logic.services.arrange.environment import ENV_TAG, OBJECT_TYPE_BY_FORMAT, SECOND_TYPE_AT
from logicxkit.logic.services.arrange.stacks import read_tracks
from logicxkit.logic.services.song.arrangement_write import ARRANGEMENT_TRACK_TYPE
from logicxkit.logic.services.stream.stream import project_records
from logicxkit.logic.services.stream.stream import HEADER
from logicxkit.logic.services.stream.validate import file_format, validate_project
from logicxkit.logicx import project_data

FAMILIES = ("rename", "levels", "route", "send", "bypass", "add-plugin", "remove-plugin", "replace-plugin", "swap-plugin",
            "clear-slots", "add-track", "colour", "hide", "reorder", "group", "markers", "arrangement", "tempo", "signature",
            "metronome", "width", "stack-create", "stacks-move", "midi", "automation", "beats-place")
OURS = {f: (f"{f}-ours-13-0", f"{f}-ours-resave-13-0-logic") for f in FAMILIES}
READERS = {"rename": ["stacks", "--tracks"], "levels": ["levels"], "route": ["project"], "send": ["project"], "bypass": ["plugins"],
           "add-plugin": ["plugins"], "remove-plugin": ["plugins"], "replace-plugin": ["plugins"], "swap-plugin": ["plugins"],
           "clear-slots": ["plugins"], "add-track": ["stacks", "--tracks"], "colour": ["stacks", "--tracks"], "hide": ["stacks", "--tracks"],
           "reorder": ["stacks", "--tracks"], "group": ["group"], "markers": ["markers"], "arrangement": ["arrangement"],
           "tempo": ["tempo"], "signature": ["signature"], "metronome": ["metronome"], "width": ["width"],
           "stack-create": ["stacks", "--tracks"], "stacks-move": ["stacks", "--tracks"], "midi": ["midi"],
           "automation": ["automation"], "beats-place": ["midi"]}
CHANNEL_KEYED, SHOWN_WORD, ROW_MARK, ROW_FLAGS, TYPE_WORDS, ROW_UUID = (80,), (30,), (43,), (2,), (0, 1, 114, 115), range(24, 40)
KEYED_CHANNEL = {(b"OCuA", 9, 65535, 0): CHANNEL_KEYED}          # the Klopfgeist channel on the two-track twin
OBJECT_TYPE = (b"ivnE", 65535, 65535, 13)                        # a new object written from a 12.x template: 1800 -> 1312


def every(tag: bytes, offsets: tuple, owners, key: int = 65535, n: int = 0, but=()) -> dict:
    return {(tag, o, key, n): offsets for o in owners if o not in but}


# family -> (records only ours has, records only Logic's has, {(tag, owner, key, n): offsets or ("length", ours, logic)})
EXPECTED = {
    "rename": ([], [], KEYED_CHANNEL),
    "levels": ([], [], KEYED_CHANNEL),
    "route": ([], [], KEYED_CHANNEL),
    "send": ([], [], {**KEYED_CHANNEL, (b"UCuA", 0, 0, 0): (0,), OBJECT_TYPE: TYPE_WORDS,
                      (b"karT", 65535, 6, 0): tuple(i for i in ROW_UUID if i not in (30, 31))}),
    "bypass": ([], [], {}),
    "add-plugin": ([], [], {**KEYED_CHANNEL, (b"OCuA", 0, 65535, 1): (81,)}),
    "remove-plugin": ([(b"UCuA", 0, 15, 1392), (b"UCuA", 10, 15, 348), (b"UCuA", 11, 15, 831)],
                      [(b"UCuA", 0, 13, 4136), (b"UCuA", 10, 14, 348), (b"UCuA", 11, 13, 1921)],
                      {**every(b"OCuA", SHOWN_WORD, range(1, 274), but=(10, 11)), (b"nCuA", 65535, 65535, 1): (61,),
                       (b"OCuA", 0, 65535, 1): ("length", 265, 261), (b"OCuA", 10, 65535, 0): ("length", 265, 261),
                       (b"OCuA", 11, 65535, 0): ("length", 265, 261), (b"UCuA", 0, 14, 0): ("length", 4136, 1392),
                       (b"UCuA", 11, 14, 0): ("length", 1921, 831)}),
    "replace-plugin": ([(b"UCuA", 0, 16, 1392), (b"UCuA", 10, 16, 348), (b"UCuA", 11, 16, 831)],
                       [(b"UCuA", 0, 14, 2016), (b"UCuA", 10, 15, 348), (b"UCuA", 11, 14, 1921)],
                       {(b"OCuA", 0, 65535, 1): ("length", 269, 265), (b"OCuA", 10, 65535, 0): ("length", 269, 265),
                        (b"OCuA", 11, 65535, 0): ("length", 269, 265), (b"UCuA", 0, 15, 0): ("length", 2016, 1392),
                        (b"UCuA", 11, 15, 0): ("length", 1921, 831)}),
    "swap-plugin": ([(b"UCuA", 0, 16, 1392), (b"UCuA", 10, 16, 348), (b"UCuA", 11, 16, 831)],
                    [(b"UCuA", 0, 14, 5357), (b"UCuA", 10, 15, 348), (b"UCuA", 11, 14, 1921)],
                    {(b"OCuA", 0, 65535, 1): ("length", 269, 265), (b"OCuA", 10, 65535, 0): ("length", 269, 265),
                     (b"OCuA", 11, 65535, 0): ("length", 269, 265), (b"UCuA", 0, 15, 0): ("length", 5357, 1392),
                     (b"UCuA", 11, 15, 0): ("length", 1921, 831)}),
    "clear-slots": ([(b"UCuA", 0, 14, 5357), (b"UCuA", 0, 15, 1392), (b"UCuA", 10, 15, 348), (b"UCuA", 11, 14, 1921), (b"UCuA", 11, 15, 831)],
                    [(b"UCuA", 0, 7, 303), (b"UCuA", 0, 8, 907), (b"UCuA", 10, 8, 348), (b"UCuA", 11, 7, 1921), (b"UCuA", 11, 8, 831)],
                    {**every(b"OCuA", SHOWN_WORD, range(1, 274), but=(10, 11)), (b"nCuA", 65535, 65535, 1): (61,),
                     (b"OCuA", 0, 65535, 1): ("length", 265, 237), (b"OCuA", 10, 65535, 0): ("length", 265, 237),
                     (b"OCuA", 11, 65535, 0): ("length", 265, 237)}),
    "add-track": ([], [], {(b"OCuA", 10, 65535, 0): CHANNEL_KEYED, (b"karT", 65535, 2, 0): ROW_MARK,
                           (b"karT", 65535, 6, 0): tuple(i for i in ROW_UUID if i not in (30, 31))}),
    "colour": ([], [], KEYED_CHANNEL),
    "hide": ([], [], KEYED_CHANNEL),
    "reorder": ([], [], {**KEYED_CHANNEL, (b"karT", 65535, 0, 1): ROW_MARK}),
    "group": ([], [], KEYED_CHANNEL),
    "markers": ([], [], {}),
    "arrangement": ([], [], {**KEYED_CHANNEL, (b"snrT", 65535, 65535, 0): TYPE_WORDS}),
    "tempo": ([], [], {}),
    "signature": ([], [], {**KEYED_CHANNEL, (b"ivnE", 65535, 65535, 1): (222, 223, 278, 279)}),
    "metronome": ([], [], KEYED_CHANNEL),
    "width": ([], [], {**KEYED_CHANNEL, (b"OCuA", 0, 65535, 1): (94, 95, 185, 191, 193, 194)}),
    "stack-create": ([], [], {**KEYED_CHANNEL, OBJECT_TYPE: TYPE_WORDS, (b"karT", 65535, 0, 1): ROW_FLAGS,
                              (b"karT", 65535, 6, 0): (2,) + tuple(i for i in ROW_UUID if i not in (28, 30, 31))}),
    "stacks-move": ([], [], {(b"OCuA", 10, 65535, 0): CHANNEL_KEYED}),
    "midi": ([], [], {}),
    "automation": ([], [], {(b"OCuA", 1, 65535, 0): (89,), (b"vEuA", 80, 10, 0): (3, 21)}),
    "beats-place": ([], [], {(b"karT", 65535, 1, 0): (2, 43)}),
}


# family -> (input key, argv with {project}; {db} and {id} name a pattern from the synthetic library)
FRESH = {"send": ("tracks-two-audio-13-0-logic", ["send", "--add", "Audio 1=Bus 1", "{project}"]),
         "stack-create": ("tracks-two-audio-13-0-logic", ["stack-create", "--name", "Drums", "--track", "Audio 1", "--track", "Audio 2", "{project}"]),
         "arrangement": ("tracks-two-audio-13-0-logic", ["arrangement", "--add", "1:8:Intro:custom", "{project}"]),
         "add-track": ("tracks-two-audio-13-0-logic", ["add-track", "--name", "Audio 3", "--after", "Audio 2", "{project}"]),
         "beats-place": ("tracks-instrument-13-0-logic", ["beats", "place", "{project}", "{id}", "--track", "Inst 1", "--bar", "1", "--db", "{db}"])}
TYPED = ("send", "stack-create", "arrangement", "add-track")          # the fresh writes that make an object
# family -> the `qSvE` payloads only ours holds, set against Logic's (`sequence_differences`): the signature record's events
# in the other order, the same 16-byte lines
SEQUENCES = {"signature": [(96, REORDERED)]}


def data(key: str) -> bytes:
    return project_data(_goldens.path(key))


def fresh(family: str) -> bytes:
    """The family's write on its 13.0 twin, made now with the format gate opened for the run."""
    key, argv = FRESH[family]
    out = io.StringIO()
    with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(out), \
            mock.patch("logicxkit.logic.cli.formats", lambda cmd: (2513, 2514)):
        subs = {"project": str(_goldens.path(key))}
        if "{db}" in argv:
            db = index(Path(tmp) / "library")
            subs |= {"db": str(db), "id": beat(db, "Verse 01")["id"]}
        code = logicxkit_main(["logic", *(a.format(**subs) for a in argv), "--out", tmp])
        if code != 0:
            raise AssertionError(out.getvalue())
        return project_data(next(Path(tmp).glob("*.logicx")))


def type_words(d: bytes) -> list[tuple[bytes, int, int]]:
    return [(r.tag, struct.unpack_from("<H", r.raw, HEADER)[0], struct.unpack_from("<H", r.raw, HEADER + SECOND_TYPE_AT)[0])
            for r in project_records(d) if r.tag in (ENV_TAG, b"snrT") and len(r.raw) > HEADER + SECOND_TYPE_AT + 2]


def tracks(d: bytes, count: int) -> list[dict]:
    """The arrange rows as read, the flag words Logic's re-save rewrites left out."""
    return [{k: v for k, v in t.items() if k not in ("flag", "expanded")} for t in read_tracks(d, count)]


def shown(key: str, argv: list[str]) -> list[str]:
    """A reader's output on the save, its bundle name blanked and the display-state tempo line dropped."""
    path = _goldens.path(key)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = logicxkit_main(["logic", argv[0], str(path), *argv[1:]])
    if code != 0:
        raise AssertionError(out.getvalue())
    return [ln.replace(path.name, "<bundle>").replace(path.stem, "<bundle>") for ln in out.getvalue().splitlines() if "shown at save" not in ln]


@_goldens.needs(*(k for pair in OURS.values() for k in pair))
class LogicsReSaveOfEachWriteTest(unittest.TestCase):
    def test_each_pair_is_a_2514_project_that_validates_and_reads_the_same(self):
        for family, (ours, logic) in OURS.items():
            with self.subTest(family=family):
                a, b = data(ours), data(logic)
                self.assertEqual((file_format(a), file_format(b)), (2514, 2514))
                self.assertEqual((validate_project(a), validate_project(b)), ([], []))
                count = _goldens.fact(ours, "tracks")
                self.assertEqual(tracks(a, count), tracks(b, count))          # names, colours, hidden, depth, membership
                self.assertEqual(shown(ours, READERS[family]), shown(logic, READERS[family]))

    def test_logic_kept_every_record_but_what_expected_pins(self):
        for family, (ours, logic) in OURS.items():
            with self.subTest(family=family):
                only_ours, only_logic, changed = compared(records(ours), records(logic))
                ids = lambda rs: [(r.tag, r.owner, r.key, len(r.raw) - HEADER) for r in rs]        # noqa: E731
                self.assertEqual((ids(only_ours), ids(only_logic), changed), EXPECTED[family])

    def test_a_fresh_write_gives_its_new_object_the_formats_type_word(self):
        """The staged send, stack-create and arrangement writes carry their 12.x templates' type words, which
        Logic 13.0's re-saves rewrote; the writers write 13.0's (1312 on an object, 640 on the arrangement track), so no 12.x
        word is left in a write on a 13.0 save. `send` makes its aux through `addtrack.add_track` from the packaged
        12.x template, so it is the case that exercises that call; `add-track` itself clones one of the project's own
        objects and is held here to the same outcome."""
        twelve = {OBJECT_TYPE_BY_FORMAT[2513], ARRANGEMENT_TRACK_TYPE[2513]}
        for family in TYPED:
            with self.subTest(family=family):
                words = type_words(fresh(family))
                self.assertEqual([w for w in words if w[1] in twelve or w[2] in twelve], [])
                new = (b"snrT", ARRANGEMENT_TRACK_TYPE[2514], ARRANGEMENT_TRACK_TYPE[2514]) if family == "arrangement" \
                    else (ENV_TAG, OBJECT_TYPE_BY_FORMAT[2514], OBJECT_TYPE_BY_FORMAT[2514])
                self.assertEqual(words[0] if family == "arrangement" else words[-1], new, words)   # the new record: the track first, an object last
        self.assertEqual([w for w in type_words(data(OURS["send"][0])) if w[1] in twelve], [(ENV_TAG, 1800, 1800)])

    def test_a_fresh_arrangement_write_is_logics_re_save_but_for_the_keyed_channel_byte(self):
        only_ours, only_logic, changed = compared([r for r in project_records(fresh("arrangement")) if r.tag not in CHURN],
                                                  records(OURS["arrangement"][1]))
        self.assertEqual((only_ours, only_logic, changed), ([], [], KEYED_CHANNEL))

    def test_a_fresh_beats_place_is_logics_re_save_but_for_the_churn(self):
        """The staged write left the instrument row's content flags (`+2` 0x14, `+43` 0x0c) to Logic;
        `midi_write.add_region` now sets them, so nothing outside the per-save churn differs."""
        only_ours, only_logic, changed = compared([r for r in project_records(fresh("beats-place")) if r.tag not in CHURN],
                                                  records(OURS["beats-place"][1]))
        self.assertEqual((only_ours, only_logic, changed), ([], [], {}))

    def test_a_fresh_stack_create_is_logics_re_save_but_for_the_keyed_byte_and_the_minted_uuids(self):
        """The staged write left the header row's selected flag and its mixer-order row's `+2` to Logic; the writers
        now set both. What still differs is minted on every write: the new Sub strip's, object's and two rows' UUIDs."""
        minted = {(b"karT", 65535, 0, 1): ROW_UUID, (b"karT", 65535, 6, 0): ROW_UUID,
                  (b"ivnE", 65535, 65535, 13): range(469 - 16, 469), (b"OCuA", 269, 65535, 0): range(153, 169)}
        only_ours, only_logic, changed = compared([r for r in project_records(fresh("stack-create")) if r.tag not in CHURN],
                                                  records(OURS["stack-create"][1]))
        self.assertEqual((only_ours, only_logic, {k: v for k, v in changed.items() if k not in minted}), ([], [], KEYED_CHANNEL))
        for key, span in minted.items():
            self.assertLessEqual(set(changed.get(key, ())), set(span), (key, changed.get(key)))

    def test_the_sequence_records_differ_where_sequences_pins(self):
        """`compared` drops the `qSvE` records as churn; set against each other as payload multisets, every pair's agree
        but signature's: Logic 13.0 wrote the signature record's events (a 96-byte record: the meter event with its 16-byte
        line, the key event, a 16-byte tail) in the other order, the key before the meter."""
        for family, (ours, logic) in OURS.items():
            with self.subTest(family=family):
                self.assertEqual(sequence_differences(ours, logic), SEQUENCES.get(family, []))

    def test_thirteen_families_come_back_as_written(self):
        """Nothing but a channel's `+80` (8 on the channel with keyed records) and a row's cleared mark, read off the
        staged pairs."""
        clean = set()
        for f, (ours, logic) in OURS.items():
            a, b, changed = compared(records(ours), records(logic))
            if not a and not b and all(v in (CHANNEL_KEYED, ROW_MARK) for v in changed.values()):
                clean.add(f)
        self.assertEqual(sorted(clean), ["bypass", "colour", "group", "hide", "levels", "markers", "metronome", "midi",
                                         "rename", "reorder", "route", "stacks-move", "tempo"])


if __name__ == "__main__":
    unittest.main()
