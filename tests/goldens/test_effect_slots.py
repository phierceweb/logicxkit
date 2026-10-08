"""One effect per save on the blank instrument project's Inst 1 (`instrument-fx-<name>-logic`;
the `effect` fact is the row chosen in the slot's menu): Logic's MIDI effects, which sit in a
slot kind of their own, and three audio effects."""

import tempfile
import unittest
from pathlib import Path

import _goldens
from logicxkit.logic._edit import owner_by_label
from logicxkit.logic.services.mixer.donors import harvest_donors
from logicxkit.logic.services.mixer.plugin_library import load_library
from logicxkit.logic.services.mixer.plugin_names import native_name, native_names
from logicxkit.logic.services.mixer.plugins import project_plugins
from logicxkit.logic.services.mixer.slot_identity import slot_header
from logicxkit.logic.services.mixer.slot_width import plugin_variant
from logicxkit.logic.services.mixer.transplant import channel_slots
from logicxkit.logic.services.project.project import analyze
from logicxkit.logic.services.stream.stream import HEADER, project_records
from logicxkit.logicx import project_data

KEYS = tuple(k for k in sorted(_goldens.manifest()) if k.startswith("instrument-fx-") and _goldens.fact(k, "slot"))
MIDI = tuple(k for k in KEYS if _goldens.fact(k, "slot") == "midi")
PEDALS = tuple(k for k in KEYS if _goldens.fact(k, "pedal_category"))
AUDIO = tuple(k for k in KEYS if _goldens.fact(k, "slot") == "audio" and k not in PEDALS)
MASTERING = "instrument-fx-mastering-assistant-logic"


def _added(key: str):
    """(project, the record Logic added, its owner)."""
    data = project_data(_goldens.path(key))
    owner = owner_by_label(data, _goldens.fact(key, "channel"))
    record = next(r for r in project_records(data)
                  if r.tag == b"UCuA" and r.owner == owner and r.key == _goldens.fact(key, "key"))
    return data, record, owner


@_goldens.needs(*KEYS)
class EffectSlotsTest(unittest.TestCase):
    def test_the_menus_rows_are_all_here(self):
        self.assertEqual((len(MIDI), len(AUDIO)), (9, 4))

    def test_the_slot_header_names_the_plug_in(self):
        for key in KEYS:
            with self.subTest(key):
                head, want = slot_header(_added(key)[1].raw[HEADER:]), _goldens.fact(key, "header")
                self.assertEqual((head.name, head.maker, head.word, head.code, head.instrument),
                                 (want["name"], want["maker"], want["word"], want["code"], False))

    def test_plugins_lists_the_effect_by_the_menu_rows_name(self):
        for key in KEYS:
            with self.subTest(key):
                data, record, _owner = _added(key)
                ref = next(r for r in project_plugins(data)
                           if r.channel == _goldens.fact(key, "channel") and r.key == record.key)
                self.assertEqual((ref.name, ref.native, ref.midi),
                                 (_goldens.fact(key, "effect"), True, _goldens.fact(key, "slot") == "midi"))

    def test_a_midi_effect_is_kind_two_at_its_own_key_and_no_insert(self):
        """The record sits one key under the strip reference's place with index 0: not among
        the channel's audio slots, and not in the insert chain `project` prints."""
        for key in MIDI:
            with self.subTest(key):
                data, record, owner = _added(key)
                self.assertEqual((_goldens.fact(key, "kind"), record.raw[HEADER + 6]), (2, 0))
                self.assertTrue(slot_header(record.raw[HEADER:]).midi)
                self.assertNotIn(record.key, [r.key for r in channel_slots(data, owner)])
                chains = {c["label"]: c["chain"] for c in analyze(data)["channels"]}
                self.assertEqual(chains.get(_goldens.fact(key, "channel"), []), [])

    def test_an_audio_effect_is_the_channels_second_slot(self):
        for key in AUDIO:
            with self.subTest(key):
                data, record, owner = _added(key)
                self.assertEqual([r.key for r in channel_slots(data, owner)][-1], record.key)
                self.assertFalse(slot_header(record.raw[HEADER:]).midi)


@_goldens.needs(*PEDALS)
class StompboxesTest(unittest.TestCase):
    """Pedalboard's pedals, one per save from the Stompboxes rows of the Audio FX menu: every
    one is type 273 and is told from the others by its variant base, as its header word also
    does."""

    def test_every_pedal_of_the_menu_is_here(self):
        self.assertEqual(len(PEDALS), 35)
        self.assertEqual(sorted({_goldens.fact(k, "pedal_category") for k in PEDALS}),
                         ["Delay", "Distortion", "Dynamics", "Filter", "Modulation", "Pitch"])

    def test_a_pedal_is_type_273_under_its_own_variant_base_and_word(self):
        bases, words = {}, {}
        for key in PEDALS:
            payload = _added(key)[1].raw[HEADER:]
            head = slot_header(payload)
            with self.subTest(key):
                self.assertEqual((head.maker, head.code, head.name), ("EMAG", 273, _goldens.fact(key, "header")["name"]))
                self.assertEqual(native_name(273, plugin_variant(payload)), _goldens.fact(key, "effect"))
            bases[plugin_variant(payload)], words[head.word] = key, key
        self.assertEqual((len(bases), len(words)), (len(PEDALS), len(PEDALS)))

    def test_each_pedal_harvests_as_a_donor_of_its_own(self):
        """`donors` files a pedal under Pedalboard's type and the pedal's variant base, labelled
        as the menu names it; no two pedals share a library key."""
        keys = []
        with tempfile.TemporaryDirectory() as tmp:
            for key in PEDALS:
                data, _record, owner = _added(key)
                harvest_donors(data, Path(tmp) / key, native_names(), owners={owner})
                donors = load_library([Path(tmp) / key])
                with self.subTest(key):
                    self.assertEqual([d.label for d in donors], [_goldens.fact(key, "effect")])
                    self.assertTrue(donors[0].key.startswith("273v"), donors[0].key)
                keys += [d.key for d in donors]
        self.assertEqual(len(set(keys)), len(PEDALS))

    def test_the_pedals_block_is_pedalboards(self):
        """One block typed 273, far shorter than the whole Pedalboard's 2001 floats."""
        for key in PEDALS:
            with self.subTest(key):
                self.assertEqual(_goldens.fact(key, "block_types"), [273])
                self.assertLess(_goldens.fact(key, "slot_bytes"), 400)


@_goldens.needs(MASTERING)
class MasteringAssistantTest(unittest.TestCase):
    """Mastering Assistant, which no Audio FX menu lists: the output strip's own Mastering slot
    puts it on the output channel as an ordinary effect slot of type 320."""

    def test_it_is_an_effect_slot_of_its_own_type_on_the_output_channel(self):
        data, record, _owner = _added(MASTERING)
        head = slot_header(record.raw[HEADER:])
        self.assertEqual((head.name, head.maker, head.code, head.instrument, head.midi), ("Mastering", "EMAG", 320, False, False))
        self.assertEqual(_goldens.fact(MASTERING, "state"), "GAMETSPP")
        ref = next(r for r in project_plugins(data) if r.key == record.key and r.channel == _goldens.fact(MASTERING, "channel"))
        self.assertEqual((ref.name, ref.native), ("Mastering Assistant", True))
        self.assertNotEqual(_goldens.fact(MASTERING, "channel"), "Inst 1")


if __name__ == "__main__":
    unittest.main()
