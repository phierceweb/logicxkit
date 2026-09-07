"""An aux fed from an instrument's extra output: the 68-byte record under the aux, the
source id and kind on its channel. Synthetic here; the goldens are Logic's saves 82 and 83
and the template's three Drums MIDI auxes, checked when present.

The real-file part of tests/logic/test_instout.py; skips without the owner's files."""

import unittest
import _goldens
import _paths
from logicxkit.logic.services.insert import HEADER, project_records
from logicxkit.logic.services.instout import (
    SIZE,
    bind_instrument_output,
    read_instrument_outputs,
)

TEMPLATE = _paths.staged("Mix")
SAVE = _goldens.path("aux-inst-out")


@unittest.skipIf(not TEMPLATE.exists(), "the Mix template is not present")
class TemplateBindingsTest(unittest.TestCase):
    def test_the_templates_drum_auxes_read_back(self):
        from logicxkit.logicx import project_data
        got = read_instrument_outputs(project_data(TEMPLATE))
        names = sorted(b.name for b in got.values())
        self.assertEqual(names, ["Addictive 13-14", "Addictive 15-16", "Addictive D 5"])
        self.assertTrue(all(b.instrument == 2 and b.plugin == "xlnA/aumu/xAD2" for b in got.values()))
        self.assertEqual(sorted(b.source_id for b in got.values()), [26, 27, 34])


@unittest.skipIf(SAVE is None, "Logic's binding save is not present")
class GoldenBindingTest(unittest.TestCase):
    def test_binding_as_logic_did_gives_logics_record_and_id(self):
        """Save 82 bound Hi Hat MIDI to Addictive 13-14 of Inst 9 in a project with twenty
        inputs and no other binding: Logic wrote id 20 (its next save gave 15-16 and D 5 the
        ids 21 and 22; that file was lost)."""
        from logicxkit.logicx import project_data
        logic = read_instrument_outputs(project_data(SAVE))
        by_name = {b.name: b for b in logic.values()}
        self.assertEqual({n: b.source_id for n, b in by_name.items()}, {"Addictive 13-14": 20})
        self.assertTrue(all(b.instrument == 9 and b.key == 12 for b in logic.values()))
        # rebuild the first binding on a copy stripped of all three and compare bytes but the UUID
        data = project_data(SAVE)
        recs = project_records(data)
        hi = by_name["Addictive 13-14"]
        kept = []
        for r in recs:
            if r.tag == b"UCuA" and len(r.raw) - HEADER == SIZE and r.owner in logic:
                continue
            raw = r.raw
            if r.tag == b"OCuA" and r.owner == hi.aux_owner and r.key == 0xFFFF and len(raw) - HEADER > 96:
                buf = bytearray(raw)
                buf[HEADER + 94:HEADER + 96] = b"\0\0"          # the source id and kind go too
                raw = bytes(buf)
            kept.append(raw)
        stripped = data[:24] + b"".join(kept)
        stripped = stripped[:16] + (len(stripped) - 24).to_bytes(4, "little") + stripped[20:]
        from logicxkit.logic.services.keyflags import sync_key_flags
        stripped = sync_key_flags(stripped)
        out = bind_instrument_output(stripped, hi.aux_owner, pattern=hi.raw, instrument=9)
        mine = read_instrument_outputs(out)[hi.aux_owner]
        self.assertEqual((mine.key, mine.source_id, mine.raw[:52]), (hi.key, 20, hi.raw[:52]))


if __name__ == "__main__":
    unittest.main()
