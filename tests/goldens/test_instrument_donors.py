"""A built-in instrument harvested from Logic's own save and written into another project's
empty instrument slot (`instrument-<name>-logic` into `instrument-control-logic`): the library
names it as the slot menu does, and the write gives the slot Logic's own record and the channel
the width Logic's own load gave it."""

import tempfile
import unittest
from pathlib import Path

import _goldens
from logicxkit.logic._edit import owner_by_label
from logicxkit.logic.services.mixer.add_plugin import add_plugin
from logicxkit.logic.services.mixer.donors import harvest_donors
from logicxkit.logic.services.mixer.mixer import CHANNEL_TAG
from logicxkit.logic.services.mixer.plugin_library import find_donor, load_library
from logicxkit.logic.services.mixer.plugin_names import native_names
from logicxkit.logic.services.mixer.remove_plugin import remove_plugin
from logicxkit.logic.services.mixer.transplant import channel_slots
from logicxkit.logic.services.stream.stream import HEADER, NO_KEY, project_records
from logicxkit.logicx import project_data

CONTROL = "instrument-control-logic"
KEYS = tuple(k for k in sorted(_goldens.manifest())
             if k.startswith("instrument-") and _goldens.fact(k, "plugin") and _goldens.fact(k, "header"))
WIDTH_AT = (78, 86, 123)


def _width(data: bytes, owner: int) -> tuple[int, ...]:
    record = next(r for r in project_records(data) if r.tag == CHANNEL_TAG and r.owner == owner and r.key == NO_KEY)
    return tuple(record.raw[HEADER + at] for at in WIDTH_AT)


@_goldens.needs(CONTROL, *KEYS)
class InstrumentDonorsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.saves = {key: project_data(_goldens.path(key)) for key in KEYS}
        cls.libraries = {}
        for key, data in cls.saves.items():          # one library a save: the Studio four share nothing by key
            library = Path(cls.tmp.name) / key
            harvest_donors(data, library, native_names(), owners={owner_by_label(data, _goldens.fact(key, "channel"))})
            cls.libraries[key] = load_library([library])

    def test_each_save_gives_one_donor_named_as_the_menu_names_it(self):
        for key in KEYS:
            with self.subTest(key):
                self.assertEqual([d.label for d in self.libraries[key]], [_goldens.fact(key, "plugin")])

    def test_no_two_instruments_share_a_library_key(self):
        keys = [d.key for key in KEYS for d in self.libraries[key]]
        self.assertEqual(len(set(keys)), len(KEYS), sorted(k for k in keys if keys.count(k) > 1))

    def test_written_into_the_empty_slot_it_is_logics_own_slot_and_width(self):
        control = project_data(_goldens.path(CONTROL))
        owner = owner_by_label(control, _goldens.fact(CONTROL, "channel"))
        emptied, _report = remove_plugin(control, owner, 1)
        for key in KEYS:
            with self.subTest(key):
                donor = find_donor(self.libraries[key], _goldens.fact(key, "plugin"), width=None, version=5)
                written, report = add_plugin(emptied, owner, donor.raw, at=1, type_id=donor.type_id)
                theirs = self.saves[key]
                self.assertEqual(report["position"], 1)
                self.assertEqual([r.raw for r in channel_slots(written, owner)], [r.raw for r in channel_slots(theirs, owner)])
                self.assertEqual(_width(written, owner), _width(theirs, owner))


@_goldens.needs(CONTROL, *KEYS)
class InstrumentTransplantTest(unittest.TestCase):
    """`transplant` of an instrument channel onto a new instrument track: the instrument comes
    over as Logic wrote it and the channel takes its width."""

    def test_the_channel_takes_the_instruments_slot_and_width(self):
        from logicxkit.logic.services.mixer.transplant import transplant
        control = project_data(_goldens.path(CONTROL))
        owner = owner_by_label(control, _goldens.fact(CONTROL, "channel"))
        for key in KEYS:
            with self.subTest(key):
                theirs = project_data(_goldens.path(key))
                source = owner_by_label(theirs, _goldens.fact(key, "channel"))
                written, report = transplant(theirs, control, src_owner=source, dst_owner=owner)
                self.assertEqual([r.raw for r in channel_slots(written, owner)], [r.raw for r in channel_slots(theirs, source)])
                self.assertEqual(_width(written, owner), _width(theirs, source))
                self.assertFalse(report["width_mismatch"])


if __name__ == "__main__":
    unittest.main()
