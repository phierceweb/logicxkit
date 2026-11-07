"""A third-party slot's state read from the bytes against what the plug-in reports through the
headless host: every id agrees on Pro-C 2's pairs and Pro-Q 4's blob, and a value the plug-in will
not keep is named."""

import json
import os
import unittest
from pathlib import Path

import _goldens

from logicxkit.au.services.austate_write import patch_ffbs
from logicxkit.au.services.embed import find_au_plists
from logicxkit.au.services.host import AuHost
from logicxkit.au.services.state_check import check_state, checkable, decoded_values
from logicxkit.logicx import project_data

PROC, PROQ = "write-proc", "translate-proq"


def fabfilter(key: str) -> dict:
    return next(pl for _off, pl in find_au_plists(project_data(_goldens.path(key)))
                if pl.get("manufacturer") == int.from_bytes(b"FabF", "big"))


def reporting(values: dict[int, float]):
    """A host that reports ``values`` for whatever state it is handed."""
    params = [{"id": i, "name": f"p{i}", "unit": "", "min": 0, "max": 1, "default": 0, "value": v} for i, v in values.items()]
    dump = {"component": "x", "type": "aumf", "subtype": "FC2p", "manufacturer": "FabF", "params": params}
    return AuHost(runner=lambda args, timeout: (0, json.dumps(dump), ""))


@_goldens.needs(PROC, PROQ)
class StateCheckTest(unittest.TestCase):
    def test_both_kinds_of_state_are_checkable(self):
        for key in (PROC, PROQ):
            with self.subTest(key):
                self.assertTrue(checkable(fabfilter(key)))

    def test_a_plug_in_reporting_the_bytes_agrees_on_every_id(self):
        plist = fabfilter(PROC)
        ours = decoded_values(plist)
        found = check_state(plist, reporting(ours))
        self.assertEqual((found.differ, found.agreed), ([], len(ours)))

    def test_a_value_the_plug_in_reports_otherwise_is_named(self):
        plist = fabfilter(PROC)
        ours = decoded_values(plist)
        first = min(ours)
        found = check_state(plist, reporting({**ours, first: ours[first] + 1}))
        self.assertEqual(found.agreed, len(ours) - 1)
        self.assertEqual(len(found.differ), 1)
        self.assertTrue(found.differ[0].startswith(f"id {first} (p{first}): bytes "), found.differ)


COMPONENTS = Path("/Library/Audio/Plug-Ins/Components")


@_goldens.needs(PROQ)
class BlobOrderTest(unittest.TestCase):
    def test_a_blob_of_an_unmeasured_plug_in_is_not_read(self):
        """Only Pro-Q 4's blob is measured to hold a value per AU id in id order; the same bytes under
        another subtype decode to nothing, so the host comparison does not run on a guess."""
        from logicxkit.au.services.state_check import checkable
        plist = dict(fabfilter(PROQ))
        self.assertTrue(checkable(plist))
        other = {**plist, "subtype": int.from_bytes(b"FL2p", "big")}
        self.assertIsNone(decoded_values(other))
        self.assertFalse(checkable(other))


def fabfilter_installed() -> bool:
    return AuHost.available() and all((COMPONENTS / f"FabFilter {n}.component").is_dir() for n in ("Pro-C 2", "Pro-Q 4"))


@_goldens.needs(PROC, PROQ)
class RealHostTest(unittest.TestCase):
    def test_the_plug_ins_read_every_id_as_the_bytes_give_it(self):
        if not fabfilter_installed():                       # a silent skip would hide a broken host on the owner's Mac
            if os.environ.get("LOGICXKIT_REQUIRE_GOLDENS") == "1":
                self.fail("the AU host and FabFilter's Pro-C 2 and Pro-Q 4 are required here")
            self.skipTest("the AU host and FabFilter's Pro-C 2 and Pro-Q 4")
        for key in (PROC, PROQ):
            with self.subTest(key):
                found = check_state(fabfilter(key), AuHost())
                self.assertEqual(found.differ, [])
                self.assertEqual(found.agreed, len(decoded_values(fabfilter(key))))

    def test_a_value_pro_q_4_will_not_keep_is_named(self):
        """Pro-Q 4 keeps a band's frequency inside its range and its shape among its shapes; Pro-C 2
        reports a pair past its range as written."""
        plist = dict(fabfilter(PROQ))
        plist["FabFilterPluginState"] = patch_ffbs(plist["FabFilterPluginState"], {2: 1e6, 5: 99})
        found = check_state(plist, AuHost())
        self.assertEqual([d.split(":")[0] for d in found.differ], ["id 2 (Band 1 Frequency)", "id 5 (Band 1 Shape)"])


if __name__ == "__main__":
    unittest.main()
