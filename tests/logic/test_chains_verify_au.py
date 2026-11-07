"""`chains --verify` reads a third-party slot through the headless AU host: the plug-in's values
against the bytes, a difference counted like a Controls row's, no host no comparison."""

import json
import unittest
import unittest.mock

import _goldens
import _paths  # noqa: F401
from goldens.test_state_check import fabfilter, reporting

from logicxkit.au.services.state_check import decoded_values
from logicxkit.logic.orchestrators.chains_verify import expected_rows, verify
from logicxkit.logicx import project_data

PROC = "write-proc"                       # Audio 2: Compressor -> Noise Gate -> Pro-C 2


def driver(argv):
    rows = expected_rows(project_data(_goldens.path(PROC)), ["Audio 2"])["Audio 2"]
    shown = [{"short": short, "rows": [{"label": k, "display": str(v)} for k, v in (values or {}).items()]}
             for _name, short, values in rows]
    return 0, json.dumps({"tracks": [{"track": "Audio 2", "strip": "Audio 2", "slots": shown}], "problems": []})


@_goldens.needs(PROC)
class ThirdPartyThroughTheHostTest(unittest.TestCase):
    def setUp(self):
        self.ours = decoded_values(fabfilter(PROC))

    def line(self, verdict) -> str:
        return next(ln for ln in verdict.lines if ln.startswith("Audio 2 / FabF/FC2p"))

    def test_a_plug_in_reading_the_bytes_matches(self):
        verdict = verify(_goldens.path(PROC), ["Audio 2"], run=driver, host=reporting(self.ours))
        self.assertEqual(self.line(verdict), f"Audio 2 / FabF/FC2p: matched through the AU host, {len(self.ours)} parameter(s)")
        self.assertTrue(verdict.matched, verdict.lines)

    def test_a_value_the_plug_in_reads_otherwise_is_a_difference(self):
        first = min(self.ours)
        verdict = verify(_goldens.path(PROC), ["Audio 2"], run=driver, host=reporting({**self.ours, first: self.ours[first] + 1}))
        self.assertTrue(self.line(verdict).startswith("Audio 2 / FabF/FC2p: 1 differ, "), verdict.lines)
        self.assertEqual(verdict.differences, 1)
        self.assertFalse(verdict.matched)



@_goldens.needs(PROC, "translate-proq")
class PairingAndBadStatesTest(unittest.TestCase):
    def test_a_third_party_slot_the_strip_lacks_does_not_shift_the_next_ones_state(self):
        """Two third-party rows, the first absent from Logic's strip: the second's line must come from
        its own state, so the host sees the second plist, never the first's."""
        from logicxkit.logic.orchestrators import chains_verify
        data = project_data(_goldens.path(PROC))
        rows = expected_rows(data, ["Audio 2"])["Audio 2"]
        third = [r for r in rows if r[2] is None]
        self.assertEqual(len(third), 1)
        plist = fabfilter(PROC)
        at = rows.index(third[0])
        doubled = rows[:at] + [("Ghost", "Ghst/XXXX", None)] + rows[at:]      # a third-party row the strip lacks, first
        seen = []

        class Host:
            def dump_preset(self, path):
                import plistlib
                seen.append(plistlib.loads(path.read_bytes()).get("name", "?"))
                return type("Dump", (), {"params": []})()

        def driver(argv):
            shown = [{"short": short, "rows": [{"label": k, "display": str(v)} for k, v in (values or {}).items()]}
                     for name, short, values in rows]
            return 0, json.dumps({"tracks": [{"track": "Audio 2", "strip": "Audio 2", "slots": shown}], "problems": []})

        first = {**plist, "name": "first"}
        second = {**plist, "name": "second"}
        with unittest.mock.patch.object(chains_verify, "expected_rows", return_value={"Audio 2": doubled}), \
             unittest.mock.patch.object(chains_verify, "third_party_states", return_value={"Audio 2": [first, second]}), \
             unittest.mock.patch.object(chains_verify, "expected_units", return_value={"Audio 2": {}}):
            verdict = verify(_goldens.path(PROC), ["Audio 2"], run=driver, host=Host())
        self.assertEqual(seen, ["second"], verdict.lines)

    def test_a_state_whose_bytes_do_not_parse_is_not_compared(self):
        from logicxkit.logic.orchestrators.chains_verify_au import host_line
        bad = {**fabfilter("translate-proq"), "FabFilterPluginState": b"garbage"}
        line, differ = host_line("Audio 2 / X", bad, reporting({}))
        self.assertEqual((line.startswith("Audio 2 / X: third-party, not compared ("), differ), (True, 0))

if __name__ == "__main__":
    unittest.main()
