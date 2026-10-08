"""Where a project no channel of which names a strip keeps its property keys: slot base + shown
slots + 1 on every Logic save on hand that carries no reference, so a project with no archive
either is read from its channel words. Skips without the public corpus."""

import plistlib
import struct
import unittest
from collections import Counter

import _goldens
from logicxkit.logic.services.arrange.addtrack import add_track
from logicxkit.logic.services.arrange.stacks import read_tracks
from logicxkit.logic.services.mixer.binding import channels
from logicxkit.logic.services.mixer.mixer import is_mixer_record
from logicxkit.logic.services.mixer.slot_identity import slot_header
from logicxkit.logic.services.mixer.slots import archive_index, property_key_base
from logicxkit.logic.services.stream.stream import HEADER, project_records
from logicxkit.logic.services.stream.validate import validate_project
from logicxkit.logicx import project_data

RESAVED = ("addtrack-inst-stereo-logic", "names-write-resave-logic")
BLANK, LOGICS_ADD = "tracks-three-audio-logic", "tracks-instrument-logic"


def _archives(data: bytes) -> dict[int, dict[int, int]]:
    """owner -> {archive number: key}."""
    out: dict[int, dict[int, int]] = {}
    for r in project_records(data):
        if r.tag == b"UCuA" and archive_index(r.raw):
            out.setdefault(r.owner, {})[archive_index(r.raw)] = r.key
    return out


def _words(data: bytes) -> set[tuple[int, int]]:
    return {struct.unpack_from("<HH", r.raw, HEADER + 28) for r in project_records(data) if is_mixer_record(r)}


@_goldens.needs(*RESAVED)
class LoneArchiveTest(unittest.TestCase):
    """Logic's re-save of a written instrument add: the new channel carries its second archive
    alone, at key 8."""

    def test_logics_own_save_is_valid(self):
        for key in RESAVED:
            with self.subTest(key=key):
                data = project_data(_goldens.path(key))
                self.assertIn({2: 8}, _archives(data).values())
                self.assertEqual(property_key_base(data), 5)
                self.assertEqual(validate_project(data), [])


@_goldens.needs(BLANK, LOGICS_ADD)
class ChannelWordsTest(unittest.TestCase):
    def test_a_project_with_no_archive_is_read_from_its_words(self):
        data = project_data(_goldens.path(BLANK))
        self.assertEqual((_archives(data), _words(data)), ({}, {(2, 2)}))
        self.assertEqual(property_key_base(data), 5)

    @_goldens.needs("instrument-fx-arpeggiator-logic", "instrument-fx-two-midi-logic")
    def test_a_second_midi_effect_moves_the_place_up_a_key_with_or_without_an_archive(self):
        from logicxkit.logic.services.stream.stream import reassemble
        for key, place in (("instrument-fx-arpeggiator-logic", 5), ("instrument-fx-two-midi-logic", 6)):
            with self.subTest(key):
                data = project_data(_goldens.path(key))
                self.assertEqual((_words(data), property_key_base(data)), ({(2, 2)}, place))
                bare = reassemble(data, [r.raw for r in project_records(data)
                                         if not (r.tag == b"UCuA" and archive_index(r.raw))])
                self.assertEqual((_archives(bare), property_key_base(bare)), ({}, place))

    def test_our_instrument_add_keys_its_archive_where_logics_own_does(self):
        data = project_data(_goldens.path(BLANK))
        with open(_goldens.path(BLANK) / "Alternatives" / "000" / "MetaData.plist", "rb") as f:
            count = plistlib.load(f)["NumberOfTracks"]
        after = read_tracks(data, count)[0]["object_id"]
        out, report = add_track(data, name="Keys", after=after, kind="instrument", track_count=count)
        logics = _archives(project_data(_goldens.path(LOGICS_ADD)))
        self.assertIn({2: 8}, logics.values())                    # the channel Logic's own add made
        self.assertEqual(_archives(out)[report["owner"]], {2: 8})
        self.assertEqual(validate_project(out), [])


ADDS = tuple(f"addtrack-inst-{layout}-logic" for layout in ("shown-3", "shown-4", "shown-5", "base-3"))


@_goldens.needs(*ADDS)
class LogicsOwnAddTest(unittest.TestCase):
    """Track > New Software Instrument Track at four layouts: the new channel carries its second
    archive alone at slot base + shown slots + 4."""

    def test_the_new_channels_archive_follows_the_words(self):
        for key in ADDS:
            with self.subTest(key=key):
                data = project_data(_goldens.path(key))
                new, slot_base, shown, at = (_goldens.fact(key, f) for f in ("new", "slot_base", "shown", "archive_key"))
                owner = next(o for o, c in channels(data).items() if c.label == new)
                self.assertEqual(_words(data), {(slot_base, shown)})
                self.assertEqual((_archives(data)[owner], at), ({2: at}, slot_base + shown + 4))
                self.assertEqual(property_key_base(data), slot_base + shown + 1)


def _logic_saves() -> list[str]:
    return sorted(k for k, e in _goldens.manifest().items() if isinstance(e, dict)
                  and str(e.get("path", "")).endswith(".logicx") and "logic" in k.split("-"))


class EveryLogicSaveTest(unittest.TestCase):
    def test_the_validator_passes_logics_own_file(self):
        saves = [(key, bundle) for key in _logic_saves() if (bundle := _goldens.path(key)) is not None]
        if not saves:
            self.skipTest("no public corpus on this machine")
        faulted = {key: problems for key, bundle in saves if (problems := validate_project(project_data(bundle)))}
        self.assertEqual(faulted, {})

    def test_the_base_is_slot_base_plus_shown_slots_plus_one_without_a_reference(self):
        fits, misfits = 0, []
        for key in _logic_saves():
            bundle = _goldens.path(key)
            if bundle is None:
                continue
            data = project_data(bundle)
            records, words = project_records(data), _words(data)
            bases = {k - 1 - n for found in _archives(data).values() for n, k in found.items() if n in (1, 2)}
            # a record at the base is a reference (a strip's or a patch's): its headroom is the project's own
            referenced = any(r.tag == b"UCuA" and r.key in bases and archive_index(r.raw) is None for r in records)
            if not bases or referenced or len(words) != 1:
                continue
            (slot_base, shown), = words
            # MIDI effects sit under the reference's place: one fits there, a second moves it a key
            midi = Counter(r.owner for r in records if r.tag == b"UCuA" and (h := slot_header(r.raw[HEADER:])) and h.midi)
            if bases == {slot_base + shown + 1 + max(0, max(midi.values(), default=0) - 1)}:
                fits += 1
            else:
                misfits.append((key, slot_base, shown, sorted(bases)))
        if not fits and not misfits:
            self.skipTest("no public corpus on this machine")
        self.assertEqual(misfits, [])
        self.assertGreater(fits, 300)


if __name__ == "__main__":
    unittest.main()
