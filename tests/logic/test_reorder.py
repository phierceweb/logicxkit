"""Arrange-row moves. A real drag (Ride above Hi Hat, 2026-09-01) renumbered two keys and
touched nothing else, so a same-parent move is a splice plus renumber."""

import unittest
from _records import chan, env_obj, proj, track, uuid
from logicxkit.logic.services.arrange.reorder import move_track
from logicxkit.logic.services.arrange.stacks import read_stacks, read_tracks


def session():
    return proj(
        env_obj(192, "Drums", grouping=True), env_obj(88, "Kick In"), env_obj(136, "Hi Hat"),
        env_obj(140, "Ride"), env_obj(212, "Drums"), env_obj(216, "Cymbals"),
        chan(378, "Sub 1", uuid=uuid(192)), chan(0, "Audio 1", uuid=uuid(88), stack_index=1),
        chan(12, "Audio 13", uuid=uuid(136), stack_index=1),
        chan(13, "Audio 14", uuid=uuid(140), stack_index=1),
        chan(68, "Aux 2", uuid=uuid(212)), chan(69, "Aux 3", uuid=uuid(216)),
        track(0, 192), track(1, 88, member=True), track(2, 136, member=True),
        track(3, 140, member=True), track(4, 212), track(5, 216))


def nested():
    """Drums holds Kick In and the stack Cymbals (Hi Hat, Ride); an aux and a room track follow."""
    return proj(
        env_obj(192, "Drums", grouping=True), env_obj(88, "Kick In"), env_obj(193, "Cymbals", grouping=True),
        env_obj(136, "Hi Hat"), env_obj(140, "Ride"), env_obj(212, "Drums"), env_obj(216, "Room"),
        chan(378, "Sub 1", uuid=uuid(192)), chan(0, "Audio 1", uuid=uuid(88), stack_index=1),
        chan(379, "Sub 2", uuid=uuid(193), stack_index=1),
        chan(12, "Audio 13", uuid=uuid(136), stack_index=2), chan(13, "Audio 14", uuid=uuid(140), stack_index=2),
        chan(68, "Aux 2", uuid=uuid(212)), chan(69, "Aux 3", uuid=uuid(216)),
        track(0, 192), track(1, 88, member=1), track(2, 193, member=1), track(3, 136, member=2),
        track(4, 140, member=2), track(5, 212), track(6, 216))


def _rows(data, count=6):
    return [(r["name"], r["depth"]) for r in read_tracks(data, count)]


class NestedMoveTest(unittest.TestCase):
    def test_a_header_moves_with_its_nested_stack(self):
        out = move_track(nested(), 192, after=216, track_count=6)
        self.assertEqual(_rows(out), [("Drums", 0), ("Room", 0), ("Drums", 0), ("Kick In", 1),
                                      ("Cymbals", 1), ("Hi Hat", 2), ("Ride", 2)])
        self.assertEqual([(s.name, [n for _k, n in s.members]) for s in read_stacks(out, 6)],
                         [("Drums", ["Kick In", "Cymbals"]), ("Cymbals", ["Hi Hat", "Ride"])])

    def test_a_nested_header_moves_with_its_members(self):
        out = move_track(nested(), 193, before=88, track_count=6)
        self.assertEqual(_rows(out)[:5], [("Drums", 0), ("Cymbals", 1), ("Hi Hat", 2), ("Ride", 2), ("Kick In", 1)])
        self.assertEqual([(s.name, [n for _k, n in s.members]) for s in read_stacks(out, 6)],
                         [("Drums", ["Cymbals", "Kick In"]), ("Cymbals", ["Hi Hat", "Ride"])])


class MoveTest(unittest.TestCase):
    def test_before_within_a_stack(self):
        out = move_track(session(), 140, before=136, track_count=5)
        self.assertEqual([r["name"] for r in read_tracks(out, 5)],
                         ["Drums", "Kick In", "Ride", "Hi Hat", "Drums", "Cymbals"])
        self.assertEqual([r["key"] for r in read_tracks(out, 5)], list(range(6)))
        self.assertEqual([n for _k, n in read_stacks(out, 5)[0].members], ["Kick In", "Ride", "Hi Hat"])

    def test_after_at_top_level(self):
        out = move_track(session(), 212, after=216, track_count=5)
        self.assertEqual([r["name"] for r in read_tracks(out, 5)][-2:], ["Cymbals", "Drums"])

    def test_only_row_bytes_change(self):
        """The two rows swap places; no other record is touched."""
        from logicxkit.logic.services.stream.recdiff import diff_records
        data = session()
        out = move_track(data, 140, before=136, track_count=5)
        self.assertEqual(len(out), len(data))
        d = diff_records(data, out)
        self.assertEqual((d.added, d.removed), ([], []))
        # the rows, plus the selection Logic moves with them (`ivnE +80`, three gnoS fields)
        self.assertEqual({c.tag for c in d.changed} - {b"karT", b"ivnE", b"gnoS"}, set())
        for c in d.changed:                      # offsets are record offsets: 36 + payload
            if c.tag == b"ivnE":
                self.assertEqual(set(c.offsets), {36 + 80})
            if c.tag == b"gnoS":
                self.assertTrue(set(c.offsets) <= {36 + o for o in (94, 95, 96, 97, 210, 211, 214, 215, 216, 217)}, c.offsets)

    def test_cross_parent_is_refused(self):
        with self.assertRaises(ValueError):
            move_track(session(), 212, before=136, track_count=5)   # aux into Drums

    def test_needs_exactly_one_anchor(self):
        with self.assertRaises(ValueError):
            move_track(session(), 140, track_count=5)
