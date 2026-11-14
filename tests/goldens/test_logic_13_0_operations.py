"""The opened commands' other write operations on Logic 13.0 saves (2026-11-13): each ran on a public 13.0 twin with the
format gate opened (`<op>-ours-13-0`) and Logic 13.0 re-saved it with no change (`<op>-ours-resave-13-0-logic`). Each
pair validates, reads the same through the command's readers, and differs record by record in what `EXPECTED` pins
alone: nothing, the per-save bytes (the Klopfgeist channel's `+80`, a row's cleared `+43` mark, a re-minted mixer-order
row UUID), or what 13.0 completed or re-laid after the staged operation; the `qSvE` sequence records `compared` drops are
set against each other as payload multisets (`SEQUENCES`). Four of what 13.0 completed the writers write (`FRESH`): a
fresh write of each is set against Logic's re-save of the staged one. The write whose input holds audio
(`arrangement-fill`) ran on the unscrubbed scratch copy of its save, so Logic found the audio on open."""

import contextlib
import io
import struct
import tempfile
import unittest
from pathlib import Path

import _goldens
from goldens.test_logic_13_0_families import INSERTS_WORD, KLOPFGEIST, UUID_SPAN, shown
from goldens.test_logic_13_0_regions import CHURN, REORDERED, compared, payload_differences, records, sequence_differences
from goldens.test_logic_13_0_writers import ROW_MARK, tracks

from logicxkit.cli import main as logicxkit_main

from logicxkit.logic.services.mixer.binding import channels
from logicxkit.logic.services.mixer.levels import read_levels
from logicxkit.logic.services.mixer.mixer import is_channel_count
from logicxkit.logic.services.mixer.sends import read_sends
from logicxkit.logic.services.mixer.slots import SHOWN_AT, slot_bypassed
from logicxkit.logic.services.mixer.transplant import channel_slots
from logicxkit.logic.services.song.arrangement import TEXT_TAG, read_sections, slot_of
from logicxkit.logic.services.stream.stream import HEADER, project_records
from logicxkit.logic.services.stream.validate import file_format, validate_project
from logicxkit.logicx import project_data

OPS = ("stacks-flatten", "stacks-convert", "stacks-move-out", "automation-copy", "automation-clear", "send-remove", "send-set",
       "send-add-level", "midi-region-note", "midi-transforms", "midi-copy-delete", "add-track-instrument", "add-track-stereo",
       "markers-edit", "markers-delete", "arrangement-edit", "arrangement-delete", "arrangement-fill", "tempo-set", "tempo-ramp",
       "signature-more", "metronome-from", "group-settings", "group-assign", "route-output", "bypass-enable",
       "add-plugin-mid-bypassed", "add-plugin-stack-set", "transplant-bypass", "retrack-map", "levels-to", "header-from",
       "controlbar-from", "toolbar-from", "modes-from")
OURS = {op: (f"{op}-ours-13-0", f"{op}-ours-resave-13-0-logic") for op in OPS}
READERS = {
    "stacks-flatten": [["stacks", "--tracks"]], "stacks-convert": [["stacks", "--tracks"], ["project"]], "stacks-move-out": [["stacks", "--tracks"]],
    "automation-copy": [["automation"]], "automation-clear": [["automation"]],
    "send-remove": [["project"]], "send-set": [["project"]], "send-add-level": [["project"]],
    "midi-region-note": [["midi"]], "midi-transforms": [["midi"]], "midi-copy-delete": [["midi"]],
    "add-track-instrument": [["stacks", "--tracks"], ["plugins"]], "add-track-stereo": [["stacks", "--tracks"], ["width"]],
    "markers-edit": [["markers"]], "markers-delete": [["markers"]],
    "arrangement-edit": [["arrangement"]], "arrangement-delete": [["arrangement"]], "arrangement-fill": [["arrangement"]],
    "tempo-set": [["tempo"]], "tempo-ramp": [["tempo"]], "signature-more": [["signature"]], "metronome-from": [["metronome"]],
    "group-settings": [["group"]], "group-assign": [["group"]], "route-output": [["project"]],
    "bypass-enable": [["plugins"]], "add-plugin-mid-bypassed": [["plugins"]], "add-plugin-stack-set": [["plugins"], ["settings"]],
    "transplant-bypass": [["plugins"]], "retrack-map": [["project"]], "levels-to": [["levels"]],
    "header-from": [["header"]], "controlbar-from": [["controlbar"]], "toolbar-from": [["toolbar"]], "modes-from": [["modes"]],
}
FOLDER_KLOPFGEIST = {(b"OCuA", 10, 65535, 0): (80,)}            # the folder-stack twin's Klopfgeist channel
AUX_ROW = {(b"karT", 65535, 6, 0): UUID_SPAN}                      # the mixer-order row of an aux or track the write makes
# every channel record's slot base (owner 270's 14-byte record carries none; owners 0 and 8 change length instead)
SLOT_BASE_LOWERED = {**{(b"OCuA", o, 65535, 0): (28,) for o in range(1, 270) if o != 8}, (b"nCuA", 65535, 65535, 1): (60,),
                     (b"OCuA", 0, 65535, 1): ("length", 241, 237), (b"OCuA", 8, 65535, 0): ("length", 241, 237),
                     (b"UCuA", 8, 8, 0): ("length", 1921, 831)}
# op -> (records only ours has, records only Logic's has, {(tag, owner, key, n): offsets or ("length", ours, logic)})
EXPECTED = {
    "stacks-flatten": ([], [], {**FOLDER_KLOPFGEIST, (b"karT", 65535, 0, 1): ROW_MARK}),
    "stacks-convert": ([], [], {**FOLDER_KLOPFGEIST, (b"ivnE", 65535, 65535, 0): (63,), (b"karT", 65535, 0, 1): (2, 43),
                                (b"karT", 65535, 8, 0): UUID_SPAN}),                  # the header's flag and mark cleared, see the row
    "stacks-move-out": ([], [], {**FOLDER_KLOPFGEIST, (b"karT", 65535, 3, 0): ROW_MARK}),
    "automation-copy": ([], [(b"vEuA", 80, 7, 52)], {(b"OCuA", 0, 65535, 1): (85, 119)}),   # the lane's sentinel record and the static volume
    "automation-clear": ([(b"vEuA", 80, 10, 52)], [], {}),                                   # the emptied lane's record, dropped
    "send-remove": ([(b"UCuA", 0, 9, 303), (b"UCuA", 8, 3, 256), (b"UCuA", 8, 9, 831)],
                    [(b"UCuA", 0, 8, 303), (b"UCuA", 8, 2, 256), (b"UCuA", 8, 7, 1921)], SLOT_BASE_LOWERED),
    "send-set": ([], [], {}),
    "send-add-level": ([], [], {(b"UCuA", 0, 0, 0): (0,), **KLOPFGEIST, **AUX_ROW}),           # the send record's class word, 72 -> 68
    "midi-region-note": ([], [], {}),
    "midi-transforms": ([], [], {}),
    "midi-copy-delete": ([], [], {}),
    "add-track-instrument": ([], [], {(b"OCuA", 9, 65535, 0): (80, 81), (b"UCuA", 9, 7, 0): ("length", 1921, 303),
                                      (b"UCuA", 9, 8, 0): ("length", 831, 803), (b"UCuA", 10, 2, 0): (116, 117, 146), **AUX_ROW}),
    "add-track-stereo": ([], [], {**FOLDER_KLOPFGEIST, (b"karT", 65535, 2, 0): ROW_MARK, **AUX_ROW}),
    "markers-edit": ([], [], {}),
    "markers-delete": ([], [], {}),
    "arrangement-edit": ([], [], {}),
    "arrangement-delete": ([(b"qSxT", 65535, 65535, 104)], [], {}),                           # the deleted section's text record, dropped
    "arrangement-fill": ([(b"qSxT", 65535, 65535, 102)], [], {(b"qSxT", 65535, 65535, 2): (98, 99, 100, 101, 102),
                                                             (b"qSxT", 65535, 65535, 3): ("length", 104, 106),
                                                             (b"qSxT", 65535, 65535, 4): ("length", 106, 102)}),   # paired past the dropped one
    "tempo-set": ([], [], {}),
    "tempo-ramp": ([], [], {}),
    "signature-more": ([], [], {**KLOPFGEIST, (b"ivnE", 65535, 65535, 1): (230, 231, 232, 233, 318, 319)}),
    "metronome-from": ([], [], KLOPFGEIST),
    "group-settings": ([], [], {}),
    "group-assign": ([], [], {}),
    "route-output": ([], [], {**KLOPFGEIST, **AUX_ROW}),
    "bypass-enable": ([], [], {}),
    "add-plugin-mid-bypassed": ([], [], {}),
    "add-plugin-stack-set": ([], [], {**INSERTS_WORD, (b"OCuA", 1, 65535, 0): (81,), (b"OCuA", 2, 65535, 0): (81,), **FOLDER_KLOPFGEIST}),
    "transplant-bypass": ([], [], {**INSERTS_WORD, **FOLDER_KLOPFGEIST}),
    "retrack-map": ([], [], {}),
    "levels-to": ([], [], KLOPFGEIST),
    "header-from": ([], [], KLOPFGEIST),
    "controlbar-from": ([], [], KLOPFGEIST),
    "toolbar-from": ([], [], KLOPFGEIST),
    "modes-from": ([], [], KLOPFGEIST),
}
# op -> the `qSvE` payloads only ours holds, set against Logic's (`sequence_differences`): the later tempo event's time
# word, each group member's three fader events in the other order (the same 16-byte lines), a bit of a mode record
SEQUENCES = {"tempo-set": [(80, (56, 57))], "group-settings": [(208, REORDERED)], "modes-from": [(80, (47,))]}
# op -> the lengths of the `qSxT` text records only ours holds (a deleted section's, which 13.0 drops); Logic's holds none of its own
TEXTS = {"arrangement-delete": [104], "arrangement-fill": [104]}


def sends(d: bytes) -> dict:
    return {channels(d)[o].label: [(s.bus, s.level, s.mode, s.bypassed) for s in ss] for o, ss in read_sends(d).items()}


def outputs(d: bytes) -> dict:
    return {c.label: c.dest_uuid for c in channels(d).values() if c.label.startswith("Audio")}


def bypasses(d: bytes) -> dict:
    return {c.label: [slot_bypassed(r.raw) for r in channel_slots(d, o)] for o, c in channels(d).items() if c.label == "Audio 1"}


# what the write changed, where no reader prints it: read off the records
FIELDS = {"send-remove": sends, "send-set": sends, "send-add-level": sends, "route-output": outputs, "bypass-enable": bypasses,
          "levels-to": read_levels, "stacks-convert": lambda d: {c.label: c.in_use for c in channels(d).values()}}   # the Sub out, the Aux in
INPUT_OF = {"levels-to": "tracks-two-audio-13-0-logic"}        # the `--to` project, the one the copy is of
# the staged operations whose completion the writers write: the send record's class word by the project's format, the
# deleted section's text record dropped, the later tempo events' time words, a member's fader events in Logic's order
FRESH = {"send-add-level": ["send", "--add", "Audio 1=Bus 1", "--level", "-3", "--bypass", "on"],
         "arrangement-delete": ["arrangement", "--delete", "1"], "arrangement-fill": ["arrangement", "--delete", "2", "--fill", "Gap"],
         "tempo-set": ["tempo", "--set", "110"],
         "group-settings": ["group", "--group", "1", "--name", "Kit", "--setting", "Volume", "--setting", "Mute", "--setting", "Pan"]}
# the 16-byte UUIDs a fresh `send --add` mints, (record, offset): the send's instance UUID (`+44`), two in one channel record
# and one in another, the new object's, a row's; the mixer-order row's (`AUX_ROW`) is 13.0's re-mint, not the write's
MINTED_UUIDS = (((b"UCuA", 0, 0, 0), 44), ((b"OCuA", 7, 65535, 0), 153), ((b"OCuA", 7, 65535, 0), 185),
                ((b"OCuA", 12, 65535, 0), 153), ((b"ivnE", 65535, 65535, 13), 453), ((b"karT", 65535, 4, 0), 24))
MINTED = {k: {o for key, at in MINTED_UUIDS if key == k for o in range(at, at + 16)} for k, _at in MINTED_UUIDS}


def data(key: str) -> bytes:
    return project_data(_goldens.path(key))


def payload(rs, key: tuple) -> bytes:
    """The payload of the record `compared` names by (tag, owner, key, n)."""
    tag, owner, k, n = key
    return [r.raw[HEADER:] for r in rs if (r.tag, r.owner, r.key) == (tag, owner, k)][n]


def fresh(op: str) -> bytes:
    """The operation's write on the staged write's own input, made now."""
    cmd, *rest = FRESH[op]
    out = io.StringIO()
    with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(out):
        code = logicxkit_main(["logic", cmd, str(_goldens.path(_goldens.fact(OURS[op][0], "input"))), *rest, "--out", tmp])
        if code != 0:
            raise AssertionError(out.getvalue())
        return project_data(next(Path(tmp).glob("*.logicx")))


@_goldens.needs(*(k for pair in OURS.values() for k in pair))
class LogicsReSaveOfEachOperationTest(unittest.TestCase):
    def test_each_pair_is_a_2514_project_that_validates_and_reads_the_same(self):
        for op, (ours, logic) in OURS.items():
            with self.subTest(op=op):
                a, b = data(ours), data(logic)
                self.assertEqual((file_format(a), file_format(b)), (2514, 2514))
                self.assertEqual((validate_project(a), validate_project(b)), ([], []))
                count = _goldens.fact(ours, "tracks")
                self.assertEqual(tracks(a, count), tracks(b, count))
                for reader in READERS[op]:
                    self.assertEqual(shown(ours, reader), shown(logic, reader), reader)

    def test_logic_kept_every_record_but_what_expected_pins(self):
        for op, (ours, logic) in OURS.items():
            with self.subTest(op=op):
                only_ours, only_logic, changed = compared(records(ours), records(logic))
                ids = lambda rs: [(r.tag, r.owner, r.key, len(r.raw) - HEADER) for r in rs]        # noqa: E731
                self.assertEqual((ids(only_ours), ids(only_logic), changed), EXPECTED[op])

    def test_the_sequence_records_differ_where_sequences_pins(self):
        for op, (ours, logic) in OURS.items():
            with self.subTest(op=op):
                self.assertEqual(sequence_differences(ours, logic), SEQUENCES.get(op, []))

    def test_the_section_text_records_differ_in_the_deleted_sections_alone(self):
        """`compared` pairs the `qSxT` text records by position (they share one id), so past a dropped one it sets each
        against its neighbour; as payload multisets ours holds the deleted section's text record and Logic's nothing of
        its own."""
        for op, (ours, logic) in OURS.items():
            with self.subTest(op=op):
                self.assertEqual([(n, kind) for n, kind in sequence_differences(ours, logic, b"qSxT")],
                                 [(n, "unpaired") for n in TEXTS.get(op, [])])

    def test_each_write_shows_through_a_reader_and_logic_kept_what_it_shows(self):
        """A reader that ignores the written field would make "reads the same" vacuous: for every op some reader, or the
        records read in `FIELDS`, differ between the input and the write, and every one agrees between the write and Logic's."""
        for op, (ours, logic) in OURS.items():
            with self.subTest(op=op):
                src = INPUT_OF.get(op, _goldens.fact(ours, "input"))
                shows = [shown(src, r) != shown(ours, r) for r in READERS[op]]
                if op in FIELDS:
                    read = FIELDS[op]
                    shows.append(read(data(src)) != read(data(ours)))
                    self.assertEqual(read(data(ours)), read(data(logic)))
                self.assertTrue(any(shows), op)

    def test_the_named_words_hold_the_values_the_rows_state(self):
        """The send record's class word (72 -> 68), the slot base on every channel record and in the count record (3 -> 2),
        the Klopfgeist channel's `+80` (0 -> 8) where `EXPECTED` names them."""
        a, b = (data(k) for k in OURS["send-add-level"])
        send = lambda d: next(r.raw[HEADER] for r in project_records(d) if r.tag == b"UCuA" and r.key == 0 and len(r.raw) - HEADER == 76)   # noqa: E731
        self.assertEqual((send(a), send(b)), (72, 68))
        a, b = (data(k) for k in OURS["send-remove"])
        base = lambda d: {struct.unpack_from("<H", r.raw, HEADER + 28)[0] for r in project_records(d) if r.tag == b"OCuA" and len(r.raw) - HEADER >= SHOWN_AT}   # noqa: E731
        self.assertEqual((base(a), base(b)), ({3}, {2}))
        count = lambda d: next(r.raw[HEADER + 60] for r in project_records(d) if is_channel_count(r))    # noqa: E731
        self.assertEqual((count(a), count(b)), (3, 2))
        def word(d: bytes, owner: int, n: int) -> int:
            return [r.raw for r in project_records(d) if r.tag == b"OCuA" and r.owner == owner][n][HEADER + 80]

        for op, (ours, logic) in OURS.items():
            for (tag, owner, _key, n), offsets in EXPECTED[op][2].items():
                if tag == b"OCuA" and isinstance(offsets, tuple) and 80 in offsets:
                    self.assertEqual((word(data(ours), owner, n), word(data(logic), owner, n)), (0, 8), (op, owner))

    def test_the_operations_that_come_back_byte_for_byte(self):
        """Nothing outside the churn and nothing in the sequence records."""
        clean = set()
        for op, (ours, logic) in OURS.items():
            a, b, changed = compared(records(ours), records(logic))
            if not a and not b and not changed and not sequence_differences(ours, logic):
                clean.add(op)
        self.assertEqual(sorted(clean), ["add-plugin-mid-bypassed", "arrangement-edit", "bypass-enable", "group-assign", "markers-delete",
                                         "markers-edit", "midi-copy-delete", "midi-region-note", "midi-transforms", "retrack-map",
                                         "send-set", "tempo-ramp"])


@_goldens.needs(*(k for op in FRESH for k in OURS[op]))
class TheWritersWriteWhatLogicCompletedTest(unittest.TestCase):
    def test_a_fresh_send_add_is_logics_re_save_but_for_the_uuids_and_the_klopfgeist_byte(self):
        """The staged write carried the 12.x template's class word (72); the writer writes the project format's (68). Past
        that a fresh write differs in the UUIDs it mints, the row UUID 13.0 re-mints and the Klopfgeist byte alone, and
        its minted UUIDs agree with one another where the staged write's do."""
        made = [r for r in project_records(fresh("send-add-level")) if r.tag not in CHURN]
        only_ours, only_logic, changed = compared(made, records(OURS["send-add-level"][1]))
        masks = {**MINTED, **{k: set(v) for k, v in AUX_ROW.items()}}
        past = {k: tuple(o for o in v if o not in masks.get(k, ())) for k, v in changed.items()}
        self.assertEqual((only_ours, only_logic, {k: v for k, v in past.items() if v}), ([], [], KLOPFGEIST))
        self.assertEqual(set(changed) - set(masks), set(KLOPFGEIST))

        def same(rs) -> set[tuple[int, int]]:
            u = [payload(rs, k)[at:at + 16] for k, at in MINTED_UUIDS]
            return {(i, j) for i in range(len(u)) for j in range(i + 1, len(u)) if u[i] == u[j]}

        staged = records(OURS["send-add-level"][0])
        self.assertTrue(same(staged))
        self.assertEqual(same(made), same(staged))

    def test_a_fresh_fill_differs_from_logics_re_save_in_the_new_sections_text_slot_alone(self):
        """The fresh fill's section takes the slot the delete freed; the staged write, keeping the orphan record, took the
        next, and 13.0 dropped the orphan: the same sections through the reader, the text records paired by length."""
        made, logic = fresh("arrangement-fill"), data(OURS["arrangement-fill"][1])
        self.assertEqual([(s.name, s.start) for s in read_sections(made)], [(s.name, s.start) for s in read_sections(logic)])
        slots = lambda d: sorted(slot_of(r.raw) for r in project_records(d) if r.tag == TEXT_TAG)       # noqa: E731
        self.assertEqual((slots(made), slots(logic)), ([0, 4, 8, 12, 16], [0, 4, 12, 16, 20]))
        only_ours, only_logic, changed = compared([r for r in project_records(made) if r.tag not in CHURN], records(OURS["arrangement-fill"][1]))
        self.assertEqual((only_ours, only_logic), ([], []))
        self.assertEqual({k[0] for k in changed}, {TEXT_TAG})
        self.assertTrue(all(v[0] == "length" for v in changed.values()), changed)
        self.assertEqual((payload_differences(made, logic), payload_differences(made, logic, b"qSxT")), ([(208, (64,))], []))

    def test_a_fresh_delete_tempo_set_and_group_edit_are_logics_re_save_byte_for_byte(self):
        """The text record dropped, the later tempo point's time word moved, each member's events in Logic's order."""
        for op in ("arrangement-delete", "tempo-set", "group-settings"):
            with self.subTest(op=op):
                made, logic = fresh(op), data(OURS[op][1])
                self.assertEqual(compared([r for r in project_records(made) if r.tag not in CHURN], records(OURS[op][1])), ([], [], {}))
                self.assertEqual((payload_differences(made, logic), payload_differences(made, logic, b"qSxT")), ([], []))


if __name__ == "__main__":
    unittest.main()
