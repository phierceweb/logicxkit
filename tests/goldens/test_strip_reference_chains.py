"""The chain-by-reference example run live: `logic chains` onto the channel whose reference the
config names (`strip-reference-library-logic`), Logic's Controls views matched every row
(`chains --verify`, 2026-11-04), and Logic 12.4 re-saved the copy (`strip-reference-chains-resave-logic`).
A copy written without the key headroom (`strip-reference-chains-ours`) came back with the reference
and every channel's archives one key up; the writer lays the range out as Logic does, every channel
record byte for byte."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _goldens

from logicxkit.cli import main as logicxkit_main
from logicxkit.logic.services.mixer.binding import channels
from logicxkit.logic.services.mixer.mixer import CHANNEL_TAG
from logicxkit.logic.services.mixer.plugins import slot_payloads
from logicxkit.logic.services.mixer.transplant import reference_record
from logicxkit.logic.services.stream.stream import HEADER, project_records
from logicxkit.logic.services.stream.validate import validate_project
from logicxkit.logicx import project_data

BASE, OURS, LOGICS = "strip-reference-library-logic", "strip-reference-chains-ours", "strip-reference-chains-resave-logic"
STRIP = "strip-kick-ours"
REPO = Path(__file__).resolve().parents[2]
TOKEN_AT = 76                      # a slot payload's per-plug-in token, recomputed by Logic on load


def keyed(data: bytes) -> dict[int, list[int]]:
    """owner -> its `UCuA` keys, on the mixer channels."""
    owners = set(channels(data))
    out: dict[int, list[int]] = {}
    for r in project_records(data):
        if r.tag == b"UCuA" and r.owner in owners:
            out.setdefault(r.owner, []).append(r.key)
    return {o: sorted(k) for o, k in out.items()}


def channel_records(data: bytes) -> dict[int, bytes]:
    owners = set(channels(data))
    return {r.owner: r.raw for r in project_records(data) if r.tag == CHANNEL_TAG and r.owner in owners and len(r.raw) - HEADER > 200}


def masked_slots(data: bytes) -> list[tuple[str, str, bytes]]:
    return [(ref.channel, ref.name, payload[:TOKEN_AT] + payload[TOKEN_AT + 2:]) for ref, payload in slot_payloads(data)]


@_goldens.needs(BASE, OURS, LOGICS, STRIP)
class ChainByReferenceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        out = Path(self.tmp.name)
        config = json.loads((REPO / "config" / "example-chains.json").read_text())
        config["chains"] = {_goldens.fact(BASE, "reference"): dict(config["chains"]["Kick.cst"], label="Verify")}
        (out / "chains.json").write_text(json.dumps(config))
        with mock.patch.dict(os.environ, {"LOGICXKIT_STRIP_ROOT": str(_goldens.path(STRIP).parents[3])}):
            code = logicxkit_main(["logic", "chains", str(_goldens.path(BASE)), "--config", str(out / "chains.json"),
                                   "--out", str(out / "out")])
        self.assertEqual(code, 0)
        self.written = project_data(out / "out" / _goldens.path(BASE).name)
        self.logics = project_data(_goldens.path(LOGICS))

    def test_the_chain_lands_on_the_referenced_channel(self):
        names = [r.name for r, _p in slot_payloads(self.written) if r.channel == _goldens.fact(BASE, "channel")]
        self.assertEqual(names, _goldens.fact(LOGICS, "chain"))
        self.assertEqual(validate_project(self.written), [])

    def test_the_key_layout_and_every_channel_record_are_logics(self):
        self.assertEqual(keyed(self.written), keyed(self.logics))
        self.assertEqual(channel_records(self.written), channel_records(self.logics))
        self.assertEqual(masked_slots(self.written), masked_slots(self.logics))
        owner = next(o for o, c in channels(self.written).items() if c.label == _goldens.fact(BASE, "channel"))
        self.assertEqual(reference_record(self.written, owner), reference_record(self.logics, owner))

    def test_logic_moved_the_range_the_earlier_copy_left_in_place(self):
        before = project_data(_goldens.path(OURS))
        slots = {o: [k for k in keys if k <= 4] for o, keys in keyed(before).items()}
        self.assertEqual(keyed(before)[0], [2, 3, 4, 7, 9, 10])
        self.assertEqual(keyed(self.logics), {o: slots[o] + [k + 1 for k in keys if k > 4] for o, keys in keyed(before).items()})


if __name__ == "__main__":
    unittest.main()
