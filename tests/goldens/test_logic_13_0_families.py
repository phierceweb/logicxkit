"""The writer families beyond the one-write commands (2026-11-13): each ran on a Logic 13.0 save (2514) with the format gate opened for
the run (`<family>-ours-13-0`), and Logic 13.0 re-saved the write with no change (`<family>-ours-resave-13-0-logic`).
The families that need audio content or sections ran on `take-*-13-0-logic`: Logic 13.0's re-saves of this tool's
`regions --audio` takes of synthetic files on the public twins; `chains` and `retrack` on Logic 13.0's re-save of the
library-setting save (`strip-reference-library-13-0-logic`). Each pair validates, reads the same through the family's
readers, and differs record by record in what `EXPECTED` pins alone."""

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _goldens
from goldens.test_logic_13_0_regions import CHURN, REORDERED, compared, records, sequence_differences
from goldens.test_logic_13_0_writers import CHANNEL_KEYED, ROW_MARK, ROW_UUID, tracks

from logicxkit.cli import main as logicxkit_main
from logicxkit.logic.services.regions.audio_regions import REGION_TAG, piece_number_at
from logicxkit.logic.services.stream.stream import HEADER, project_records
from logicxkit.logic.services.stream.validate import file_format, validate_project
from logicxkit.logicx import project_data

FAMILIES = ("transplant", "tracking-chains-eq", "tracking-chains-comp", "sidechain", "apply-template", "migrate", "header",
            "controlbar", "toolbar", "modes", "settings", "settings-proc", "chains", "retrack", "quantize-drums", "songs",
            "strip-silence", "split-sections", "drums-to-midi")
OURS = {f: (f"{f}-ours-13-0", f"{f}-ours-resave-13-0-logic") for f in FAMILIES}
INPUTS = ("take-drums-13-0-logic", "take-set-13-0-logic", "take-sections-13-0-logic", "take-kit-13-0-logic",
          "strip-reference-library-13-0-logic")
READERS = {
    "transplant": [["plugins"], ["settings", "--channel", "Audio 1"]],
    "tracking-chains-eq": [["plugins"], ["settings"]], "tracking-chains-comp": [["plugins"], ["settings"]],
    "sidechain": [["plugins"]],
    "apply-template": [["stacks", "--tracks"], ["plugins"]], "migrate": [["stacks", "--tracks"]],
    "header": [["header"]], "controlbar": [["controlbar"]], "toolbar": [["toolbar"]], "modes": [["modes"]],
    "settings": [["settings", "--channel", "Audio 1"]], "settings-proc": [["settings", "--channel", "Audio 2"]],
    "chains": [["plugins"], ["project"]], "retrack": [["project"]],
    "quantize-drums": [["regions"], ["group"]], "songs": [["arrangement"], ["regions"]], "strip-silence": [["regions"]],
    "split-sections": [["regions"], ["arrangement"]], "drums-to-midi": [["midi"], ["regions"]],
}

SHOWN_MIRROR = {(b"nCuA", 65535, 65535, 1): (61,)}           # the count record's copy of the shown-slot word (`OCuA +30`)
KLOPFGEIST = {(b"OCuA", 9, 65535, 0): CHANNEL_KEYED}           # the two-track twin's Klopfgeist channel
INSERTS_WORD = {(b"OCuA", 0, 65535, 1): (81,)}                 # Audio 1's `+81`, 0 -> 2 once it carries inserts
UUID_SPAN = tuple(i for i in ROW_UUID if i not in (30, 31))    # a row UUID Logic re-mints, two bytes equal by chance
# family -> the `qSvE` payloads only ours holds, set against Logic's (`sequence_differences`): a mode bit, the drum region's
# event lines in the other order
SEQUENCES = {"modes": [(80, (47,))], "drums-to-midi": [(176, REORDERED)]}
# family -> (records only ours has, records only Logic's has, {(tag, owner, key, n): offsets or ("length", ours, logic)})
EXPECTED = {
    "transplant": ([], [], {**SHOWN_MIRROR, **INSERTS_WORD, **KLOPFGEIST}),
    "tracking-chains-eq": ([], [], {(b"UCuA", 1, 2, 0): (300, 301, 302, 316, 317, 318)}),     # two frequencies a step under
    "tracking-chains-comp": ([(b"UCuA", 0, 12, 303), (b"UCuA", 1, 12, 1391), (b"UCuA", 9, 12, 831)],
                             [(b"UCuA", 0, 11, 303), (b"UCuA", 1, 10, 5357), (b"UCuA", 9, 10, 1921)],
                             {(b"OCuA", 0, 65535, 1): ("length", 253, 249), (b"OCuA", 1, 65535, 0): ("length", 253, 249),
                              (b"UCuA", 1, 5, 0): (204,), (b"UCuA", 1, 11, 0): ("length", 5357, 1391),
                              (b"OCuA", 9, 65535, 0): ("length", 253, 249), (b"UCuA", 9, 11, 0): ("length", 1921, 831)}),
    "sidechain": ([], [], INSERTS_WORD),
    "apply-template": ([], [], {**SHOWN_MIRROR, **INSERTS_WORD, (b"OCuA", 10, 65535, 0): (80, 81),
                                (b"UCuA", 10, 14, 0): ("length", 1921, 303), (b"UCuA", 10, 15, 0): ("length", 831, 803),
                                (b"karT", 65535, 3, 0): ROW_MARK, (b"karT", 65535, 6, 0): UUID_SPAN, (b"karT", 65535, 7, 0): UUID_SPAN}),
    "migrate": ([], [], {(b"OCuA", 10, 65535, 0): CHANNEL_KEYED, (b"karT", 65535, 6, 0): UUID_SPAN,
                         (b"karT", 65535, 7, 0): tuple(i for i in UUID_SPAN if i != 28)}),
    "header": ([], [], KLOPFGEIST),
    "controlbar": ([], [], KLOPFGEIST),
    "toolbar": ([], [], KLOPFGEIST),
    "modes": ([], [], KLOPFGEIST),
    "settings": ([], [], {}),
    "settings-proc": ([], [], {}),
    "chains": ([], [], {**SHOWN_MIRROR, (b"UCuA", 0, 3, 0): (76, 77)}),                      # the new slot's per-plug-in token
    "retrack": ([], [], {}),
    "quantize-drums": ([], [], {(b"lFuA", 65535, 65535, 0): (432, 444, 445), (b"lFuA", 65535, 65535, 1): (434, 446, 447)}),
    "songs": ([], [], {}),
    "strip-silence": ([], [], {(b"gRuA", 1, 65535, 0): (134,), (b"gRuA", 2, 65535, 0): (134,)}),
    "split-sections": ([], [], {(b"gRuA", 1, 65535, 0): (142,), (b"gRuA", 2, 65535, 0): (142,), (b"gRuA", 3, 65535, 0): (142,),
                                (b"karT", 65535, 1, 0): (2, 43)}),
    "drums-to-midi": ([], [], {}),
}


# family -> (input key, argv with {project}; {src:KEY} another public save, {config} the chain config keyed by the save's reference)
FRESH = {"transplant": ("tracks-two-audio-13-0-logic", ["transplant", "{src:inserts-native-all-13-0-logic}", "{project}", "--channel", "Audio 1=Audio 1"]),
         "chains": ("strip-reference-library-13-0-logic", ["chains", "{project}", "--config", "{config}"]),
         "apply-template": ("tracks-two-audio-13-0-logic", ["apply-template", "{src:inserts-native-all-13-0-logic}", "{project}"]),
         "split-sections": ("take-sections-13-0-logic", ["split-sections", "{project}", "--section", "break", "--track", "Audio 1", "--to", "Audio 2"])}
ROOT = _goldens.CORPUS.parents[1]


def data(key: str) -> bytes:
    return project_data(_goldens.path(key))


def fresh(family: str) -> bytes:
    """The family's write on its 13.0 input, made now with the format gate opened for the run; `chains` with the example
    config keyed by the save's own reference and the corpus strips as the strip root."""
    key, argv = FRESH[family]
    out = io.StringIO()
    with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(out), \
            mock.patch("logicxkit.logic.cli.formats", lambda cmd: (2513, 2514)), \
            mock.patch.dict(os.environ, {"LOGICXKIT_STRIP_ROOT": str(_goldens.path("strip-kick-ours").parents[3])}):
        config = Path(tmp, "chains.json")
        example = json.loads((ROOT / "config/example-chains.json").read_text())
        example["chains"] = {"CLAUDE Verify.cst": {**example["chains"]["Kick.cst"], "label": "Verify"}}
        config.write_text(json.dumps(example))
        words = [str(_goldens.path(a[5:-1])) if a.startswith("{src:") else a.format(project=str(_goldens.path(key)), config=str(config)) for a in argv]
        code = logicxkit_main(["logic", *words, "--out", str(Path(tmp, "out"))])
        if code != 0:
            raise AssertionError(out.getvalue())
        return project_data(next(Path(tmp, "out").glob("*.logicx")))


def shown(key: str, argv: list[str]) -> list[str]:
    """A reader's output on the save, its bundle name blanked and the per-run lines dropped."""
    path = _goldens.path(key)
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = logicxkit_main(["logic", argv[0], str(path), *argv[1:]])
    if code != 0:
        raise AssertionError(out.getvalue())
    return [ln.replace(path.name, "<bundle>").replace(path.stem, "<bundle>") for ln in out.getvalue().splitlines()
            if "shown at save" not in ln and "auval scan" not in ln]


@_goldens.needs(*INPUTS)
class TheInputsTest(unittest.TestCase):
    def test_each_input_is_a_valid_2514_save(self):
        for key in INPUTS:
            with self.subTest(key):
                d = data(key)
                self.assertEqual(file_format(d), 2514)
                self.assertEqual(validate_project(d), [])


@_goldens.needs(*(k for pair in OURS.values() for k in pair))
class LogicsReSaveOfEachFamilyTest(unittest.TestCase):
    def test_each_pair_is_a_2514_project_that_validates_and_reads_the_same(self):
        for family, (ours, logic) in OURS.items():
            with self.subTest(family=family):
                a, b = data(ours), data(logic)
                self.assertEqual((file_format(a), file_format(b)), (2514, 2514))
                self.assertEqual((validate_project(a), validate_project(b)), ([], []))
                count = _goldens.fact(ours, "tracks")
                self.assertEqual(tracks(a, count), tracks(b, count))
                for reader in READERS[family]:
                    self.assertEqual(shown(ours, reader), shown(logic, reader), reader)

    def test_logic_kept_every_record_but_what_expected_pins(self):
        for family, (ours, logic) in OURS.items():
            with self.subTest(family=family):
                only_ours, only_logic, changed = compared(records(ours), records(logic))
                ids = lambda rs: [(r.tag, r.owner, r.key, len(r.raw) - HEADER) for r in rs]        # noqa: E731
                self.assertEqual((ids(only_ours), ids(only_logic), changed), EXPECTED[family])

    def test_the_piece_number_sits_past_the_name_on_logics_re_saves(self):
        """Names of 10 and 17 bytes (the second padded to 18): the byte `piece_number_at` names holds each cut record's
        owner on Logic's re-save, 0 on the uncut record — at `+134` and `+142`, not the d-series' `+136`."""
        for key, at in (("strip-silence-ours-resave-13-0-logic", 134), ("split-sections-ours-resave-13-0-logic", 142)):
            with self.subTest(key):
                cut = [r for r in project_records(data(key)) if r.tag == REGION_TAG and r.owner]
                self.assertGreaterEqual(len(cut), 2)
                self.assertEqual({piece_number_at(r.raw[HEADER:]) for r in cut}, {at})
                self.assertEqual([r.raw[HEADER + piece_number_at(r.raw[HEADER:])] for r in cut], [r.owner for r in cut])
                self.assertEqual([r.raw[HEADER + 136] for r in cut if at != 136], [0] * len(cut))

    def test_a_fresh_transplant_is_logics_re_save_but_for_the_inserts_word_and_the_keyed_byte(self):
        """The staged write left the count record's copy of the shown-slot word to Logic; `show_slots` now writes it."""
        only_ours, only_logic, changed = compared([r for r in project_records(fresh("transplant")) if r.tag not in CHURN],
                                                  records(OURS["transplant"][1]))
        self.assertEqual((only_ours, only_logic, changed), ([], [], {**INSERTS_WORD, **KLOPFGEIST}))

    def test_a_fresh_chains_write_is_logics_re_save_but_for_the_new_slots_token(self):
        only_ours, only_logic, changed = compared([r for r in project_records(fresh("chains")) if r.tag not in CHURN],
                                                  records(OURS["chains"][1]))
        self.assertEqual((only_ours, only_logic, changed), ([], [], {(b"UCuA", 0, 3, 0): (76, 77)}))

    def test_a_fresh_apply_template_differs_in_what_logic_regenerates_and_the_minted_uuids_alone(self):
        """The staged write left the count record's copy of the shown-slot word to Logic; `show_slots` now writes it. What
        a fresh write mints anew: the two new channels' trailers, the two new objects' and six rows' UUIDs."""
        minted = {(b"OCuA", 2, 65535, 0): range(153, 169), (b"OCuA", 11, 65535, 0): range(217, 233),
                  (b"ivnE", 65535, 65535, 13): range(453, 469), (b"ivnE", 65535, 65535, 14): range(455, 471),
                  **{(b"karT", 65535, k, n): ROW_UUID for k, n in ((1, 0), (2, 1), (3, 0), (5, 0), (6, 0), (7, 0))}}
        only_ours, only_logic, changed = compared([r for r in project_records(fresh("apply-template")) if r.tag not in CHURN],
                                                  records(OURS["apply-template"][1]))
        expected = {k: v for k, v in EXPECTED["apply-template"][2].items() if k not in SHOWN_MIRROR}
        self.assertEqual((only_ours, only_logic, {k: v for k, v in changed.items() if k not in minted}),
                         ([], [], {k: v for k, v in expected.items() if k not in minted}))
        past_the_mint = lambda offsets: {k: tuple(o for o in offsets.get(k, ()) if o not in set(span)) for k, span in minted.items()}  # noqa: E731
        self.assertEqual({k: v for k, v in past_the_mint(changed).items() if v}, {k: v for k, v in past_the_mint(expected).items() if v})

    def test_a_fresh_split_sections_write_is_logics_re_save_but_for_the_piece_numbers(self):
        """The staged write left the destination row's content flags to Logic; `move_to_track` now writes them."""
        only_ours, only_logic, changed = compared([r for r in project_records(fresh("split-sections")) if r.tag not in CHURN],
                                                  records(OURS["split-sections"][1]))
        self.assertEqual((only_ours, only_logic, changed), ([], [], {(b"gRuA", o, 65535, 0): (142,) for o in (1, 2, 3)}))

    def test_the_sequence_records_differ_where_sequences_pins(self):
        """`compared` drops the `qSvE` records as churn; as payload multisets every pair's agree but two: 13.0 set a bit
        of a mode record after `modes` (`+47`) and wrote the drums-to-midi region's event lines in the other order, the same
        16-byte lines."""
        for family, (ours, logic) in OURS.items():
            with self.subTest(family=family):
                self.assertEqual(sequence_differences(ours, logic), SEQUENCES.get(family, []))

    def test_the_families_that_come_back_as_written(self):
        """Nothing but a channel's `+80` and a row's cleared mark, the sequence records included, read off the staged pairs."""
        clean = set()
        for f, (ours, logic) in OURS.items():
            a, b, changed = compared(records(ours), records(logic))
            if not a and not b and all(v in (CHANNEL_KEYED, ROW_MARK) for v in changed.values()) and not sequence_differences(ours, logic):
                clean.add(f)
        self.assertEqual(sorted(clean), ["controlbar", "header", "retrack", "settings", "settings-proc", "songs", "toolbar"])


if __name__ == "__main__":
    unittest.main()
