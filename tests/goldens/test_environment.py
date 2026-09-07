"""Environment objects: the `ivnE` records that name tracks and stack folders.

`+16` object id, `+38` parent (u32 — bytes +39..41 are zero on every object in seven sessions,
and 192/196 read back as the id where set), `+154` kind, `+158` u16-length name, and the
instance UUID in the last 16 bytes. Payload length is 463 or 464 plus the name length.

The real-file part of tests/logic/test_environment.py; skips without the owner's files."""

import unittest



class NextObjectIdAvoidsTrackRowsTest(unittest.TestCase):
    """`karT` rows reference object ids too, and Logic's `ivnE` records do not always reach the
    highest of them. Scanning only `ivnE` handed out an id a row already used, so the new object
    and an existing row claimed the same id — a duplicate flat mixer row."""

    def _sessions(self):
        import _paths
        root = _paths.RESOURCES
        return sorted(p for d in ("legacy", "mixes") for p in (root / d).rglob("*.logicx"))

    def test_no_real_session_hands_back_an_id_a_row_already_uses(self):
        from logicxkit.logic.services.environment import next_object_id
        from logicxkit.logic.services.insert import project_records
        from logicxkit.logic.services.tracklist import arrange_run, row_object
        projects = self._sessions()
        if not projects:
            self.skipTest("no sessions under resources/legacy or resources/mixes")
        for project in projects:
            with self.subTest(project.stem):
                data = sorted(project.glob("Alternatives/*/ProjectData"))[0].read_bytes()
                records = project_records(data)
                rows = {row_object(records[i].raw) for i in arrange_run(records)}
                self.assertNotIn(next_object_id(records), rows)


if __name__ == "__main__":
    unittest.main()
