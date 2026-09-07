"""One document for a project's template-level shape, built only from decoded fields."""

import unittest
from _records import chan, env_obj, proj, send, track, uuid
from logicxkit.logic.services.manifest import manifest_from_bytes


def _session():
    return proj(
        env_obj(192, "Drums", grouping=True), env_obj(88, "Kick In"), env_obj(212, "Drm"),
        chan(378, "Sub 1", uuid=uuid(192), fader=88),
        chan(0, "Audio 1", uuid=uuid(88), dest=uuid(1001), stack_index=1, fader=99, pan=0),
        chan(121, "Bus 1", uuid=uuid(1001), size=201),
        send(0, 0, 15), chan(135, "Bus 15", uuid=uuid(15), size=201),
        track(0, 192), track(1, 88, member=True))


class ManifestTest(unittest.TestCase):
    def test_tracks_and_stacks(self):
        m = manifest_from_bytes(_session(), track_count=1)
        self.assertEqual([t["name"] for t in m["tracks"]], ["Drums", "Kick In"])
        self.assertEqual(m["tracks"][1]["stack"], "Drums")
        self.assertEqual(m["stacks"], [{"name": "Drums", "index": 1, "owner": 378,
                                        "fader": 88, "members": ["Kick In"]}])

    def test_channel_row(self):
        m = manifest_from_bytes(_session(), track_count=1)
        row = next(c for c in m["channels"] if c["label"] == "Audio 1")
        self.assertEqual(row["object"], "Kick In")
        self.assertEqual(row["output"], "Bus 1")
        self.assertEqual(row["sends"], [{"slot": 0, "bus": 15, "to": "Bus 15"}])
        self.assertEqual((row["fader"], row["pan"], row["width"], row["stack_index"]),
                         (99, 0, 2, 1))

    def test_unbound_stubs_are_left_out(self):
        m = manifest_from_bytes(proj(chan(26, "Audio 27", in_use=False)))
        self.assertEqual(m["channels"], [])


class DuplicateNameTest(unittest.TestCase):
    def test_a_header_named_like_its_member_is_not_inside_its_own_stack(self):
        data = proj(
            env_obj(272, "Drums MIDI", grouping=True), env_obj(268, "Drums MIDI"),
            chan(384, "Sub 7", uuid=uuid(272)), chan(86, "Inst 2", uuid=uuid(268), stack_index=7),
            track(0, 272), track(1, 268, member=True))
        m = manifest_from_bytes(data, track_count=1)
        self.assertEqual([(t["name"], t["stack"]) for t in m["tracks"]],
                         [("Drums MIDI", None), ("Drums MIDI", "Drums MIDI")])
