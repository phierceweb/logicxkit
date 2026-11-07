"""Logic 13.0's re-saves of this tool's own writes, format 2513 in, 2514 out: the chains copy on the
library-setting save comes back with the key layout and every channel record 12.4's re-save gave it
(`strip-reference-chains-resave-13-0-logic` beside `strip-reference-chains-resave-logic`) but for the value
8 in the channel record's +80, which 13.0 sets on the channels carrying keyed records, and the
crossfade split comes back with its track entries as written, the edited bit aside
(`regions-c05-crossfade-split-ours-resave-13-0-logic`, a copy whose edited bit sits on the parent)."""

import tempfile
import unittest
from pathlib import Path

import _goldens

from logicxkit.cli import main as logicxkit_main
from logicxkit.logic.services.arrange.stacks import arrange_run
from logicxkit.logic.services.mixer.binding import channels
from logicxkit.logic.services.mixer.mixer import CHANNEL_TAG
from logicxkit.logic.services.regions.audio_regions import read_audio_regions
from logicxkit.logic.services.regions.regions import ENTRY, song_container
from logicxkit.logic.services.stream.stream import HEADER, project_records
from logicxkit.logic.services.stream.validate import file_format
from logicxkit.logicx import project_data

CHAINS_12, CHAINS_13 = "strip-reference-chains-resave-logic", "strip-reference-chains-resave-13-0-logic"
SPLIT_BASE, SPLIT_13 = "regions-a20-crossfade-logic", "regions-c05-crossfade-split-ours-resave-13-0-logic"
EDITED_AT, EDITED_BIT = 13, 0x01
FLAGS_AT = 80


def keyed(data: bytes) -> dict[int, list[tuple[int, int]]]:
    owners = set(channels(data))
    out: dict[int, list[tuple[int, int]]] = {}
    for r in project_records(data):
        if r.tag == b"UCuA" and r.owner in owners:
            out.setdefault(r.owner, []).append((r.key, len(r.raw)))
    return {o: sorted(v) for o, v in out.items()}


def channel_records(data: bytes) -> dict[int, bytes]:
    owners = set(channels(data))
    return {r.owner: r.raw for r in project_records(data) if r.tag == CHANNEL_TAG and r.owner in owners and len(r.raw) - HEADER > 200}


def entries(data: bytes) -> dict[str, bytes]:
    records = project_records(data)
    payload = records[song_container(records, arrange_run(records, None)).end].raw[HEADER:]
    return {r.name: payload[r.at:r.at + ENTRY] for r in read_audio_regions(data)}


@_goldens.needs(CHAINS_12, CHAINS_13)
class ChainsUnder13Test(unittest.TestCase):
    def test_the_key_layout_and_channel_records_are_what_12_4_gave(self):
        old, new = project_data(_goldens.path(CHAINS_12)), project_data(_goldens.path(CHAINS_13))
        self.assertEqual((file_format(old), file_format(new)), (2513, 2514))
        self.assertEqual({o: [k for k, _n in v] for o, v in keyed(new).items()}, {o: [k for k, _n in v] for o, v in keyed(old).items()})
        before, after = channel_records(old), channel_records(new)
        mask = lambda raw: raw[:HEADER + FLAGS_AT] + b"\0" + raw[HEADER + FLAGS_AT + 1:]  # noqa: E731
        self.assertEqual({o: mask(r) for o, r in after.items()}, {o: mask(r) for o, r in before.items()})
        labels = {o: c.label for o, c in channels(new).items()}
        flagged = {labels[o]: (before[o][HEADER + FLAGS_AT], after[o][HEADER + FLAGS_AT]) for o in before if before[o] != after[o]}
        self.assertEqual(flagged, {"Audio 1": (4, 12), "Inst 1": (0, 8)})       # +80 value 8: 13.0's, on the two channels with keyed records


@_goldens.needs(SPLIT_BASE, SPLIT_13)
class SplitUnder13Test(unittest.TestCase):
    def test_the_entries_come_back_as_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            code = logicxkit_main(["logic", "regions", str(_goldens.path(SPLIT_BASE)), "--split", "6=1.375", "--out", str(out)])
            self.assertEqual(code, 0)
            ours = entries(project_data(out / _goldens.path(SPLIT_BASE).name))
        theirs = entries(project_data(_goldens.path(SPLIT_13)))
        mask = lambda e: e[:EDITED_AT] + bytes([e[EDITED_AT] & ~EDITED_BIT]) + e[EDITED_AT + 1:]  # noqa: E731
        self.assertEqual({n: mask(e) for n, e in ours.items()}, {n: mask(e) for n, e in theirs.items()})
        pieces = {r.name: (r.piece, r.crossfaded) for r in read_audio_regions(project_data(_goldens.path(SPLIT_13)))}
        self.assertEqual((pieces["v030-tone2.1"], pieces["v030-tone2.2"]), ((1, True), (2, False)))


if __name__ == "__main__":
    unittest.main()
