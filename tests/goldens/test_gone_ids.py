"""Several object ids gone at once (`gone-d*-logic`: two tracks deleted on stackid-s2, then a
new track and a new folder stack): Logic's add and create each take the lowest gone id, wherever
its entry is parked, and `add-track` and `stack-create` reproduce both saves."""

import unittest

import _goldens
from _stackview import load, obj, view
from logicxkit.logic.services.arrange.addtrack import add_track
from logicxkit.logic.services.arrange.environment import channel_objects
from logicxkit.logic.services.arrange.stack_create import create_stack
from logicxkit.logic.services.arrange.stack_ids import free_object_id
from logicxkit.logic.services.stream.registry import GNOS_TAG, gone_object_ids
from logicxkit.logic.services.stream.sequence import index_table, sequences, table_entry, triple_by_slot
from logicxkit.logic.services.stream.stream import HEADER, project_records

GONE = tuple(f"gone-d{i}-logic" for i in (1, 2, 3, 4)) + ("gone-i1-logic", "gone-i2-logic")
KEYS = GONE + ("stackid-c1-logic", "addtrack-lanes-before-logic", "addtrack-lanes-after-logic")


def _gone(data: bytes) -> dict[str, int]:
    records = project_records(data)
    registry = next(r.raw[HEADER:] for r in records if r.tag == GNOS_TAG)
    table = records[index_table(records)].raw[HEADER:]
    objects = channel_objects(data)
    return {str(g): table_entry(table, g)[0] for g in gone_object_ids(registry, min(objects)) if g not in objects}


@_goldens.needs(*KEYS)
class GoneIdsTest(unittest.TestCase):
    def test_each_deletion_parks_its_ids_after_the_ones_before(self):
        for key in GONE:
            with self.subTest(key):
                data, _count = load(key)
                self.assertEqual(_gone(data), _goldens.fact(key, "gone"))

    def test_logic_took_the_lowest_gone_id_for_a_track_and_for_a_header(self):
        d3, _c = load("gone-d3-logic")
        d4, _c = load("gone-d4-logic")
        self.assertEqual(obj(d3, _goldens.fact("gone-d3-logic", "new_track")), 104)
        self.assertEqual(obj(d4, _goldens.fact("gone-d4-logic", "header")), 108)

    def _triple(self, data: bytes, object_id: int) -> bytes:
        """The qeSM payload of the object's sequence triple (its kind byte at +39, the fresh word at +300)."""
        records = project_records(data)
        entry = table_entry(records[index_table(records)].raw[HEADER:], object_id)
        triple = triple_by_slot(sequences(records), entry[1])
        return records[triple.start].raw[HEADER:]

    def test_the_reused_ids_triple_and_registry_are_logics(self):
        """Beyond `view`: the reused id's sequence triple reads as Logic's, its registry entry
        carries a UUID again, and the ids still gone are Logic's."""
        d2, count = load("gone-d2-logic")
        d3, _c = load("gone-d3-logic")
        d4, _c = load("gone-d4-logic")
        out, _report = add_track(d2, name="Audio 4", after=obj(d2, "Audio 3"), member=False, stereo=True, track_count=count)
        self.assertEqual(self._triple(out, 104), self._triple(d3, 104))
        self.assertEqual(_gone(out), _gone(d3))
        out, _report = create_stack(d3, name="Sub 2", members=[obj(d3, "Audio 4")], track_count=count + 1)
        self.assertEqual(self._triple(out, 108), self._triple(d4, 108))
        self.assertEqual(_gone(out), _gone(d4))

    def test_only_an_audio_track_reuses_a_deleted_tracks_id(self):
        """An aux on `gone-d2`, and an audio track on the id a converted folder left
        (`stackid-c1-logic`), take the next id past the highest: neither is measured."""
        from logicxkit.logic.services.arrange.environment import next_object_id
        d2, count = load("gone-d2-logic")
        _out, report = add_track(d2, name="Aux", after=obj(d2, "Audio 3"), kind="aux", member=False, track_count=count)
        self.assertEqual(report["object_id"], next_object_id(project_records(d2)))
        c1, count = load("stackid-c1-logic")
        _out, report = add_track(c1, name="Audio 6", after=obj(c1, "Audio 5"), member=False, stereo=True, track_count=count)
        self.assertEqual(report["object_id"], next_object_id(project_records(c1)))

    def test_add_track_takes_the_lowest_gone_id_as_logic_did(self):
        d2, count = load("gone-d2-logic")
        d3, _c = load("gone-d3-logic")
        records = project_records(d2)
        self.assertEqual(free_object_id(records, channel_objects(d2), count), (104, True))
        out, report = add_track(d2, name="Audio 4", after=obj(d2, "Audio 3"), member=False, stereo=True, track_count=count)
        self.assertEqual(report["object_id"], 104)
        self.maxDiff = None
        self.assertEqual(view(out, count + 1), view(d3, count + 1))

    def test_an_audio_track_takes_a_deleted_instrument_tracks_id_as_logic_did(self):
        """`gone-i1-logic`: Inst 1 deleted; Logic's New Audio Track took its id (`gone-i2-logic`).
        `add-track` takes it too, with Logic's triple, registry and strips: the free stubs are
        mono, so the stereo track gets a fresh strip where the first of them was."""
        i1, count = load("gone-i1-logic")
        i2, _c = load("gone-i2-logic")
        out, report = add_track(i1, name="Audio 4", after=obj(i1, "Audio 2"), member=None, stereo=True, track_count=count)
        self.assertEqual((report["object_id"], obj(i2, "Audio 4")), (104, _goldens.fact("gone-i2-logic", "took")))
        self.assertEqual(self._triple(out, 104), self._triple(i2, 104))
        self.assertEqual(_gone(out), _gone(i2))
        self.maxDiff = None
        self.assertEqual(view(out, count + 1), view(i2, count + 1))

    def test_a_stereo_track_on_mono_stubs_gets_a_fresh_strip_as_logic_did(self):
        """`addtrack-lanes-after-logic`: Logic's New Audio Track (stereo) with Audio 4 and 5 free
        mono stubs inserted a fresh strip at Audio 4; the stubs and the strip above them moved up."""
        before, count = load("addtrack-lanes-before-logic")
        after, _c = load("addtrack-lanes-after-logic")
        out, _report = add_track(before, name="Audio 4", after=obj(before, "Audio 1"), member=None, stereo=True, track_count=count)
        self.maxDiff = None
        self.assertEqual(view(out, count + 1), view(after, count + 1))

    def test_a_fresh_channel_goes_where_the_first_free_stub_was(self):
        """`new_channel` on a project whose every audio strip is a bare stub, the bound ones too."""
        i1, count = load("gone-i1-logic")
        i2, _c = load("gone-i2-logic")
        out, _report = add_track(i1, name="Audio 4", after=obj(i1, "Audio 2"), member=None, stereo=True,
                                 new_channel=True, track_count=count)
        self.assertEqual(view(out, count + 1)["strips"], view(i2, count + 1)["strips"])

    def test_stack_create_takes_the_lowest_gone_id_from_the_second_index(self):
        d3, count = load("gone-d3-logic")
        d4, _c = load("gone-d4-logic")
        out, report = create_stack(d3, name="Sub 2", members=[obj(d3, "Audio 4")], track_count=count)
        self.assertEqual(report["object_id"], 108)
        self.assertEqual(view(out, count + 1), view(d4, count + 1))


TRACKED = tuple(k for k in sorted(_goldens.manifest())
                if k.startswith(("tracks-", "addtrack-", "gone-", "stackid-", "stack-", "instrument-i", "instrument-fx")))


@_goldens.needs(*TRACKED)
class KeptTripleTest(unittest.TestCase):
    def test_no_byte_of_a_tracks_triple_tells_audio_from_instrument(self):
        """Why `add-track` reuses any deleted track's id for an audio track: in every save holding
        both, an audio and an instrument track's triples differ at their ids and index alone in
        common, so a gone track's kept triple cannot say which kind of track left it."""
        from logicxkit.logic.services.mixer.binding import bound_channels, channels
        from logicxkit.logic.services.stream.sequence import QESM_KIND_AT
        from logicxkit.logicx import project_data
        diffs = []
        for key in TRACKED:
            d = project_data(_goldens.path(key))
            records = project_records(d)
            table, seqs, chans = records[index_table(records)].raw[HEADER:], sequences(records), channels(d)
            first: dict[str, bytes] = {}
            for oid, owner in sorted(bound_channels(d).items()):
                entry = table_entry(table, oid)
                triple = entry and triple_by_slot(seqs, entry[1])
                if triple and owner in chans and records[triple.start].raw[HEADER + QESM_KIND_AT] == 9:
                    first.setdefault(chans[owner].label.split()[0], records[triple.start].raw[HEADER:])
            if "Audio" in first and "Inst" in first:
                a, i = first["Audio"], first["Inst"]
                diffs.append({j for j in range(len(a)) if a[j] != i[j]})
        self.assertGreaterEqual(len(diffs), 60)
        self.assertEqual(sorted(set.intersection(*diffs)), [8, 234, 242])     # qeSM id, object id, index


if __name__ == "__main__":
    unittest.main()
