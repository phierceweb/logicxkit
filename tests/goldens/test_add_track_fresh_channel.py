"""A fresh channel from `add-track` sits where Logic puts one: its record right after the
previous channel's run, the channel records in owner order, carrying the project's slot base.
Logic's re-save of a save given three tracks dropped every plug-in when the fresh record sat at
the end of the channel records instead (`addtrack-fresh-*`). Skips without the public corpus."""

import plistlib
import struct
import unittest

import _goldens
from logicxkit.logic._edit import object_by_name
from logicxkit.logic.services.addtrack import add_track
from logicxkit.logic.services.channel_alloc import AUX_FRESH, PROJECT_WORDS, is_mixer_record
from logicxkit.logic.services.insert import CHANNEL_BASE_AT, HEADER, project_records, slot_index_base
from logicxkit.logic.services.slots import archive_index, is_plugin_slot, property_key_base
from logicxkit.logic.services.stacks import read_tracks
from logicxkit.logic.services.validate import validate_project
from logicxkit.logicx import project_data

KEY = "master-track-limiter-logic"


def _count() -> int:
    with open(_goldens.path(KEY) / "Alternatives" / "000" / "MetaData.plist", "rb") as f:
        return plistlib.load(f)["NumberOfTracks"]


def _three_adds(data: bytes) -> bytes:
    count, after = _count(), "Audio 1"
    for n in (1, 2, 3):                                   # the third finds no audio stub free
        data, _report = add_track(data, name=f"FX {n}", after=object_by_name(data, after, count),
                                  kind="audio", input_number=1, stereo=False, track_count=count)
        count, after = count + 1, f"FX {n}"
    return data


@_goldens.needs(KEY)
class FreshChannelPlacementTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.before = project_data(_goldens.path(KEY))
        cls.after = _three_adds(cls.before)

    def test_logics_own_save_keeps_its_channel_records_in_owner_order(self):
        owners = [r.owner for r in project_records(self.before) if is_mixer_record(r)]
        self.assertEqual(owners, sorted(set(owners)))

    def test_the_fresh_channel_record_keeps_the_owner_order(self):
        owners = [r.owner for r in project_records(self.after) if is_mixer_record(r)]
        self.assertEqual(owners, sorted(set(owners)))
        self.assertEqual(validate_project(self.after), [])

    def test_every_channel_record_carries_the_projects_slot_base(self):
        base = slot_index_base(self.before)
        bases = {struct.unpack_from("<H", r.raw, HEADER + CHANNEL_BASE_AT)[0]
                 for r in project_records(self.after) if is_mixer_record(r)}
        self.assertEqual(bases, {base})


def _words(raw: bytes) -> tuple[int, ...]:
    return tuple(struct.unpack_from("<H", raw, HEADER + at)[0] for at in PROJECT_WORDS)


@_goldens.needs("send-three-base-4-logic", "sidechain-proc-bus1")
class ProjectWordsTest(unittest.TestCase):
    """Neither save's words match either template's, so a fresh channel that kept its template's
    would show here."""

    def test_a_fresh_audio_or_aux_channel_carries_the_projects_words(self):
        for key in ("send-three-base-4-logic", "sidechain-proc-bus1"):
            data = project_data(_goldens.path(key))
            with open(_goldens.path(key) / "Alternatives" / "000" / "MetaData.plist", "rb") as f:
                count = plistlib.load(f)["NumberOfTracks"]
            before = {_words(r.raw) for r in project_records(data) if is_mixer_record(r)}
            after = read_tracks(data, count)[-1]["object_id"]
            for kind in ("audio", "aux"):
                with self.subTest(key=key, kind=kind):
                    out, report = add_track(data, name="New", after=after, kind=kind, new_channel=True, track_count=count)
                    self.assertEqual({_words(r.raw) for r in project_records(out) if is_mixer_record(r)}, before)
                    if kind == "aux":
                        fresh = next(r.raw[HEADER:] for r in project_records(out) if is_mixer_record(r) and r.owner == report["owner"])
                        self.assertEqual({at: fresh[at] for at in AUX_FRESH}, AUX_FRESH)


@_goldens.needs("blank-base", "sidechain-comp-bus1", "send-three-base-4-logic")
class InstrumentRecordsKeyedToTheProjectTest(unittest.TestCase):
    """A new instrument channel's defaults were measured at slot base 4, property base 12; at
    any other base they sit where that project keeps them (`legacy-migrate-keyed-mine`)."""

    def test_the_instrument_at_slot_index_0_and_the_archive_at_the_property_base_plus_3(self):
        for key in ("blank-base", "sidechain-comp-bus1", "send-three-base-4-logic"):
            with self.subTest(key=key):
                data = project_data(_goldens.path(key))
                with open(_goldens.path(key) / "Alternatives" / "000" / "MetaData.plist", "rb") as f:
                    count = plistlib.load(f)["NumberOfTracks"]
                after = read_tracks(data, count)[-1]["object_id"]
                out, report = add_track(data, name="Keys", after=after, kind="instrument", track_count=count)
                keys = {archive_index(r.raw): r.key for r in project_records(out)
                        if r.tag == b"UCuA" and r.owner == report["owner"]}
                self.assertEqual(keys, {None: slot_index_base(data), 2: property_key_base(data) + 3})
                self.assertEqual(validate_project(out), [])


def _slots(key: str) -> int:
    data = project_data(_goldens.path(key))
    base, first = property_key_base(data), slot_index_base(data)
    return sum(1 for r in project_records(data) if is_plugin_slot(r, base, first))


def _in_order(key: str) -> bool:
    owners = [r.owner for r in project_records(project_data(_goldens.path(key))) if is_mixer_record(r)]
    return owners == sorted(set(owners))


@_goldens.needs("addtrack-order-mine", "addtrack-order-logic", "addtrack-fresh-mine", "addtrack-fresh-logic")
class LogicKeptTheChainsTest(unittest.TestCase):
    def test_out_of_owner_order_every_plug_in_went(self):
        self.assertFalse(_in_order("addtrack-order-mine"))
        self.assertIn("channel records out of owner order", " ".join(validate_project(project_data(_goldens.path("addtrack-order-mine")))))
        self.assertEqual((_slots("addtrack-order-mine"), _slots("addtrack-order-logic")),
                         (_goldens.fact("addtrack-order-mine", "plugin_slots"), _goldens.fact("addtrack-order-logic", "plugin_slots")))

    def test_in_owner_order_ten_fresh_channels_kept_every_one(self):
        self.assertTrue(_in_order("addtrack-fresh-mine"))
        self.assertEqual(_slots("addtrack-fresh-mine"), _slots("addtrack-fresh-logic"))
        self.assertEqual(_slots("addtrack-fresh-logic"), _goldens.fact("addtrack-fresh-logic", "plugin_slots"))


if __name__ == "__main__":
    unittest.main()
