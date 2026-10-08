"""Instruments put into `instrument-control-logic`'s slot 1 by the commands
(`instrument-write-<name>-mine`) and Logic 12.4's re-saves of those copies (`-logic`,
2026-10-05): the commands reproduce the staged copies from their inputs, and Logic kept what was
written, adding only what it adds to its own saves."""

import tempfile
import unittest
from pathlib import Path

import _goldens
from _cli import run

from logicxkit.logic._edit import owner_by_label
from logicxkit.logic.services.mixer.add_plugin import add_plugin
from logicxkit.logic.services.mixer.donors import harvest_donors
from logicxkit.logic.services.mixer.mixer import CHANNEL_TAG
from logicxkit.logic.services.mixer.plugin_library import find_donor, load_library
from logicxkit.logic.services.mixer.plugin_names import native_names
from logicxkit.logic.services.mixer.remove_plugin import remove_plugin
from logicxkit.logic.services.mixer.slot_identity import slot_header
from logicxkit.logic.services.mixer.slots import archive_index
from logicxkit.logic.services.mixer.transplant import channel_slots
from logicxkit.logic.services.stream.stream import HEADER, NO_KEY, project_records
from logicxkit.logicx import project_data

CONTROL, LABEL = "instrument-control-logic", "Inst 1"
REPLACED = ("es2", "es-m", "drum-kit-designer", "alchemy", "studio-piano", "sampler")
TRANSPLANTED = "transplant-retro-synth"
UNTOUCHED = ("es2", "es-m", "drum-kit-designer", TRANSPLANTED)      # Logic's re-save is the copy, record for record
PAIRS = tuple(f"instrument-write-{slug}-{side}" for slug in REPLACED + (TRANSPLANTED,) for side in ("mine", "logic"))
STRIP_TAGS = (b"OCuA", b"UCuA")                                     # every channel record, slot, send and archive
OVER_EFFECT = ("instrument-fx-chromaglow-logic", "instrument-es2-logic", "instrument-es2-over-chromaglow-logic")


def _data(slug: str, side: str) -> bytes:
    return project_data(_goldens.path(f"instrument-write-{slug}-{side}"))


def _strips(data: bytes) -> list[bytes]:
    return [r.raw for r in project_records(data) if r.tag in STRIP_TAGS]


def _slot(data: bytes) -> bytes:
    return channel_slots(data, owner_by_label(data, LABEL))[0].raw


def _archives(data: bytes) -> dict[int, bytes]:
    owner = owner_by_label(data, LABEL)
    return {archive_index(r.raw): r.raw for r in project_records(data)
            if r.tag == b"UCuA" and r.owner == owner and archive_index(r.raw)}


def _width(data: bytes) -> tuple[int, ...]:
    owner = owner_by_label(data, LABEL)
    record = next(r for r in project_records(data) if r.tag == CHANNEL_TAG and r.owner == owner and r.key == NO_KEY)
    return tuple(record.raw[HEADER + at] for at in (78, 86, 123))


@_goldens.needs(CONTROL, *PAIRS)
class ReproducedTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def test_replace_plugin_writes_the_staged_copy_from_its_inputs(self):
        for slug in REPLACED:
            with self.subTest(slug):
                key = f"instrument-write-{slug}-mine"
                library, out = self.tmp / slug / "lib", self.tmp / slug / "out"
                self.assertEqual(run("donors", _goldens.path(_goldens.fact(key, "donor")), "--library", library)[0], 0)
                code, text = run("replace-plugin", _goldens.path(CONTROL), "--at", "1", "--plugin", _goldens.fact(key, "plugin"),
                                 "--channel", LABEL, "--library", library, "--out", out)
                self.assertEqual(code, 0, text)
                self.assertEqual(project_data(out / _goldens.path(CONTROL).name), _data(slug, "mine"))

    def test_transplant_writes_the_staged_copy_from_its_inputs(self):
        key = f"instrument-write-{TRANSPLANTED}-mine"
        code, text = run("transplant", _goldens.path(_goldens.fact(key, "donor")), _goldens.path(CONTROL),
                         "--channel", LABEL, "--out", self.tmp / "out")
        self.assertEqual(code, 0, text)
        self.assertEqual(project_data(self.tmp / "out" / _goldens.path(CONTROL).name), _data(TRANSPLANTED, "mine"))


@_goldens.needs(*PAIRS, "instrument-sampler-resave-logic")
class LogicKeptTest(unittest.TestCase):
    def test_logic_showed_the_instrument_in_its_slot(self):
        for slug in REPLACED + (TRANSPLANTED,):
            with self.subTest(slug):
                head = slot_header(_slot(_data(slug, "logic"))[HEADER:])
                self.assertTrue(head.instrument)
                self.assertTrue(_goldens.fact(f"instrument-write-{slug}-logic", "shown"))

    def test_four_came_back_with_every_channel_record_as_written(self):
        for slug in UNTOUCHED:
            with self.subTest(slug):
                self.assertEqual(_strips(_data(slug, "mine")), _strips(_data(slug, "logic")))

    def test_logic_made_the_smart_controls_of_studio_piano_and_alchemy_itself(self):
        for slug in ("studio-piano", "alchemy"):
            with self.subTest(slug):
                mine, logic = _archives(_data(slug, "mine")), _archives(_data(slug, "logic"))
                self.assertEqual((sorted(mine), sorted(logic)), ([2], [1, 2]))
                self.assertNotEqual(mine[2], logic[2])
        self.assertEqual(_slot(_data("studio-piano", "mine")), _slot(_data("studio-piano", "logic")))

    def test_alchemys_text_came_back_naming_the_new_project_and_nothing_else(self):
        mine, logic = (set(_slot(_data("alchemy", side))[HEADER + 172:].split(b"\r\n")) for side in ("mine", "logic"))
        changed = sorted(line.split(b" = ")[0] for line in mine ^ logic if b" = " in line)
        self.assertEqual(changed, [b"Attribs", b"Attribs", b"DataLoc", b"DataLoc"])

    def test_the_sampler_came_back_as_logics_own_sampler_save_does(self):
        resaved_own = project_data(_goldens.path("instrument-sampler-resave-logic"))
        mine, logic = _slot(_data("sampler", "mine")), _slot(_data("sampler", "logic"))
        self.assertNotEqual(len(mine), len(logic))
        self.assertEqual(logic, _slot(resaved_own))


@_goldens.needs(*OVER_EFFECT)
class OverAnEffectTest(unittest.TestCase):
    def test_a_stereo_instrument_over_a_mono_effect_leaves_logics_channel_record(self):
        """Logic kept the channel mono and its effect as it was, and set the input byte."""
        source, donor_save, theirs = (project_data(_goldens.path(k)) for k in OVER_EFFECT)
        owner = owner_by_label(source, LABEL)
        with tempfile.TemporaryDirectory() as tmp:
            harvest_donors(donor_save, Path(tmp), native_names(), owners={owner_by_label(donor_save, LABEL)})
            donor = find_donor(load_library([Path(tmp)]), "ES2", width=None, version=5)
        effect = channel_slots(source, owner)[1].raw
        emptied, _report = remove_plugin(source, owner, 1)
        written, _report = add_plugin(emptied, owner, donor.raw, at=1, type_id=donor.type_id)
        self.assertEqual(_width(theirs), (0xF3, 1, 1))
        self.assertEqual(_width(written), _width(theirs))
        self.assertEqual([r.raw for r in channel_slots(written, owner)], [donor.raw, effect])
        self.assertEqual([len(r.raw) for r in channel_slots(theirs, owner)], [len(donor.raw), len(effect)])


if __name__ == "__main__":
    unittest.main()
