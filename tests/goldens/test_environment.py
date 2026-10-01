"""Environment objects: the `ivnE` records that name tracks and stack folders.

`+16` object id, `+38` parent (u32 — bytes +39..41 are zero on every object in the sessions
measured, and nearly all read back as the id where set), `+154` kind, `+158` u16-length name,
and the instance UUID in the last 16 bytes. Payload length is 463 or 464 plus the name length.

The real-file part of tests/logic/test_environment.py; skips without the owner's files."""

import unittest

import _goldens


class NextObjectIdAvoidsTrackRowsTest(unittest.TestCase):
    """`karT` rows reference object ids too, and Logic's `ivnE` records do not always reach the
    highest of them. Scanning only `ivnE` handed out an id a row already used, so the new object
    and an existing row claimed the same id — a duplicate flat mixer row."""

    def _sessions(self):
        import _goldens
        return _goldens.sessions()

    def test_no_real_session_hands_back_an_id_a_row_already_uses(self):
        from logicxkit.logic.services.environment import next_object_id
        from logicxkit.logic.services.insert import project_records
        from logicxkit.logic.services.tracklist import arrange_run, row_object
        projects = self._sessions()
        if not projects:
            self.skipTest("no owner's session on this machine")
        for project in projects:
            with self.subTest(project.stem):
                data = sorted(project.glob("Alternatives/*/ProjectData"))[0].read_bytes()
                records = project_records(data)
                rows = {row_object(records[i].raw) for i in arrange_run(records)}
                self.assertNotIn(next_object_id(records), rows)


@_goldens.needs("names-non-ascii-logic", "tracks-three-audio-logic")
class NonAsciiNamesTest(unittest.TestCase):
    """Logic's save of two tracks renamed outside ASCII: the name is UTF-8, its length field counts
    bytes, and the rename changed the name field and the user-named bit only."""

    KEY, BASE = "names-non-ascii-logic", "tracks-three-audio-logic"

    def setUp(self):
        from logicxkit.logicx import project_data
        self.data = project_data(_goldens.path(self.KEY))
        self.base = project_data(_goldens.path(self.BASE))
        self.names = _goldens.fact(self.KEY, "names")

    def test_the_tracks_read_with_the_names_logic_shows(self):
        from logicxkit.logic.services.stacks import read_tracks
        self.assertEqual([r["name"] for r in read_tracks(self.data)][:3], self.names)

    def test_the_length_field_counts_the_names_utf8_bytes(self):
        import struct

        from logicxkit.logic.services.environment import NAME_AT, channel_objects, object_record
        from logicxkit.logic.services.insert import HEADER, project_records
        records = project_records(self.data)
        for oid, name in zip((88, 92, 96), self.names, strict=True):
            payload = object_record(records, oid)[HEADER:]
            self.assertEqual(channel_objects(self.data)[oid].name, name)
            self.assertEqual(struct.unpack_from("<H", payload, NAME_AT)[0], len(name.encode()))

    def test_logics_rename_changed_the_name_field_and_the_named_bit(self):
        from logicxkit.logic.services.environment import (
            NAME_AT, NAMED_BIT, STATE_AT, name_end, object_record)
        from logicxkit.logic.services.insert import HEADER, project_records
        before, after = project_records(self.base), project_records(self.data)

        def past_the_name(oid):
            a, b = object_record(before, oid)[HEADER:], object_record(after, oid)[HEADER:]
            ea, eb = name_end(a), name_end(b)
            return [i for i in range(len(a) - ea) if a[ea + i] != b[eb + i]]

        was, now = object_record(before, 88)[HEADER:], object_record(after, 88)[HEADER:]
        self.assertEqual([i for i in range(NAME_AT) if was[i] != now[i]], [STATE_AT])
        self.assertEqual((was[STATE_AT] & NAMED_BIT, now[STATE_AT] & NAMED_BIT), (0, 1))
        self.assertEqual(past_the_name(88), past_the_name(96), "Audio 3 was not renamed")


if __name__ == "__main__":
    unittest.main()
