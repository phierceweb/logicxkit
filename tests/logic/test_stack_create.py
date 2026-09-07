"""Creating a folder stack: the header row, the member rows, the `Sub N` strip, and the
structures a track add also needs. Logic's own Create Track Stack is unsampled; the result
opened in Logic 12.3.1 on 2026-09-02, and the real-file golden holds it to the invariants
every Logic file obeys."""

import struct
import unittest
from _records import (
    chan,
    count_record,
    env_obj,
    gnos,
    index_entry,
    marker,
    proj,
    send,
    seq_triple,
    track,
    uuid,
)
from logicxkit.logic.services.binding import channels
from logicxkit.logic.services.environment import channel_objects
from logicxkit.logic.services.insert import HEADER, project_records
from logicxkit.logic.services.sequence import sequences
from logicxkit.logic.services.stack_create import SUB_NUMBER_AT, create_stack
from logicxkit.logic.services.stacks import read_stacks, read_tracks, stack_parents
from logicxkit.logic.services.validate import validate_project

TRACKS = 8

MIXER = [88, 92, 152, 504, 212, 216, 80, 192, 196]      # the flat list's bound rows, mixer order


def sub(owner: int, number: int, *, uuid: bytes) -> bytes:
    raw = bytearray(chan(owner, f"Sub {number}", uuid=uuid, size=201))
    raw[HEADER + SUB_NUMBER_AT] = number
    return bytes(raw)


def session() -> bytes:
    """Drums(Sub 1){Kick In, Snare Up}  Bass(Sub 2){Bass DI}  Test Bounce, Drums aux, Cymbals,
    Master — with the count record, registries, index table and sequence triples a writer needs."""
    table = b"".join(index_entry(oid, 2 + k, 20 + 4 * k) for k, oid in enumerate(MIXER))
    return proj(
        count_record(12, [6, 0, 2, 1, 1, 0, 3], 12),
        gnos(88, 92, 152, 192, 196, 212, 216, 504),
        env_obj(192, "Drums", grouping=True), env_obj(88, "Kick In"), env_obj(92, "Snare Up"),
        env_obj(196, "Bass", grouping=True), env_obj(152, "Bass DI"),
        env_obj(504, "Test Bounce"), env_obj(212, "Drums"), env_obj(216, "Cymbals"),
        env_obj(80, "Master", grouping=True),
        chan(0, "Audio 1", uuid=uuid(88), stack_index=1),
        chan(2, "Audio 3", uuid=uuid(92), stack_index=1),
        chan(16, "Audio 17", uuid=uuid(152), stack_index=2),
        chan(68, "Aux 2", uuid=uuid(212)), chan(69, "Aux 3", uuid=uuid(216)),
        chan(88, "Inst 4", uuid=uuid(504)),
        sub(379, 1, uuid=uuid(192)), sub(380, 2, uuid=uuid(196)),
        chan(381, "Input 1-2", size=201, in_use=False),
        chan(382, "Output 1-2", uuid=uuid(80), size=201), send(382, 0, 5),
        seq_triple(1, big=table),
        track(0, 192), track(1, 88, member=True), track(2, 92, member=True), track(3, 196),
        track(4, 152, member=True), track(5, 504), track(6, 212), track(7, 216),
        track(8, 80, flag=3), marker(),
        *(track(k, oid) for k, oid in enumerate([296, 300, 304] + MIXER)), marker(),
        *(seq_triple(2 + k, slot=20 + 4 * k, object_id=oid, index=2 + k)
          for k, oid in enumerate(MIXER)),
        seq_triple(11, slot=100, size=341))


def names(rows: list[dict]) -> list[str]:
    return [r["name"] for r in rows]


def table_tail(data: bytes) -> bytes:
    """The last 16 bytes of a project's index table."""
    return max((r.raw[HEADER:] for r in project_records(data) if r.tag == b"qSvE"), key=len)[-16:]


class RowsTest(unittest.TestCase):
    def test_the_header_lands_where_the_first_member_sat(self):
        out, _ = create_stack(session(), name="Nested Stack", members=[504], track_count=TRACKS)
        rows = read_tracks(out, TRACKS)
        self.assertEqual(names(rows)[4:8], ["Bass DI", "Nested Stack", "Test Bounce", "Drums"])
        self.assertEqual([r["key"] for r in rows], list(range(10)))

    def test_member_bytes(self):
        out, _ = create_stack(session(), name="Nested Stack", members=[504], track_count=TRACKS)
        rows = {r["name"]: r for r in read_tracks(out, TRACKS)}
        header, member = rows["Nested Stack"], rows["Test Bounce"]
        self.assertEqual((header["member"], header["expanded"], header["grouping"]), (False, True, True))
        self.assertTrue(member["member"])
        self.assertFalse(rows["Cymbals"]["member"])

    def test_members_keep_their_arrange_order_whatever_the_call_order(self):
        out, report = create_stack(session(), name="Buses", members=[216, 212], track_count=TRACKS)
        self.assertEqual(names(read_tracks(out, TRACKS))[5:], ["Test Bounce", "Buses", "Drums", "Cymbals", "Master"])
        self.assertEqual(report["members"], [212, 216])

    def test_a_far_member_moves_up_behind_the_header(self):
        out, _ = create_stack(session(), name="Mixed", members=[504, 216], track_count=TRACKS)
        rows = read_tracks(out, TRACKS)
        self.assertEqual(names(rows)[5:], ["Mixed", "Test Bounce", "Cymbals", "Drums", "Master"])
        self.assertEqual([r["member"] for r in rows[5:]], [False, True, True, False, False])

    def test_the_flat_list_gains_a_row_after_the_last_sub(self):
        out, _ = create_stack(session(), name="Nested Stack", members=[504], track_count=TRACKS)
        flat = [r for r in project_records(out) if r.tag == b"karT" and len(r.raw) - HEADER == 58]
        ids = [struct.unpack_from("<I", r.raw, HEADER + 8)[0] for r in flat[10:]]
        self.assertEqual(ids, [296, 300, 304] + MIXER + [508])
        self.assertEqual([r.key for r in flat[10:]], list(range(13)))


class StackTest(unittest.TestCase):
    def test_reads_back_as_a_stack_on_the_next_sub(self):
        out, report = create_stack(session(), name="Nested Stack", members=[504], track_count=TRACKS)
        found = {s.name: s for s in read_stacks(out, TRACKS)}
        self.assertEqual([n for _k, n in found["Nested Stack"].members], ["Test Bounce"])
        self.assertEqual((found["Nested Stack"].index, found["Nested Stack"].owner), (3, 381))
        self.assertEqual([n for _k, n in found["Drums"].members], ["Kick In", "Snare Up"])
        self.assertEqual([n for _k, n in found["Bass"].members], ["Bass DI"])
        self.assertEqual(report, {"object_id": 508, "owner": 381, "label": "Sub 3",
                                  "sequence": 11, "slot": 56, "members": [504]})

    def test_the_sub_strip(self):
        out, _ = create_stack(session(), name="Nested Stack", members=[504], track_count=TRACKS)
        strip = next(r.raw[HEADER:] for r in project_records(out)
                     if r.tag == b"OCuA" and r.owner == 381)
        self.assertEqual(strip[SUB_NUMBER_AT], 3)
        self.assertEqual(strip[60:70], b" Sub 3\x00\x00\x00\x00")
        self.assertEqual(strip[153:169], channel_objects(out)[508].uuid)
        self.assertEqual(strip[169:], bytes(32))            # no destination, no input

    def test_members_get_the_stack_index_and_the_parent_pointer(self):
        out, _ = create_stack(session(), name="Nested Stack", members=[504], track_count=TRACKS)
        self.assertEqual(channels(out)[88].stack_index, 3)
        self.assertEqual(stack_parents(out).get(504), 508)
        self.assertEqual(channels(out)[0].stack_index, 1)

    def test_later_owners_move_up_by_one_satellites_included(self):
        out, _ = create_stack(session(), name="Nested Stack", members=[504], track_count=TRACKS)
        chans = channels(out)
        self.assertEqual((chans[380].label, chans[381].label, chans[382].label, chans[383].label),
                         ("Sub 2", "Sub 3", "Input 1-2", "Output 1-2"))
        sends = [r.owner for r in project_records(out) if r.tag == b"UCuA"]
        self.assertEqual(sends, [383])
        self.assertEqual(chans[88].label, "Inst 4")

    def test_the_object(self):
        out, _ = create_stack(session(), name="Nested Stack", members=[504], track_count=TRACKS, colour=42)
        obj = channel_objects(out)[508]
        self.assertEqual((obj.name, obj.kind, obj.colour, obj.parent), ("Nested Stack", 0, 42, 0))
        self.assertNotEqual(obj.uuid, channel_objects(out)[196].uuid)
        envs = [r for r in project_records(out) if r.tag == b"ivnE"]
        self.assertEqual(struct.unpack_from("<I", envs[-1].raw, HEADER + 16)[0], 508)

    def test_a_second_stack_takes_the_next_sub(self):
        first, _ = create_stack(session(), name="Nested Stack", members=[504], track_count=TRACKS)
        out, report = create_stack(first, name="Buses", members=[212, 216], track_count=TRACKS + 1)
        self.assertEqual((report["label"], report["owner"], report["object_id"]), ("Sub 4", 382, 512))
        found = {s.name: [n for _k, n in s.members] for s in read_stacks(out, TRACKS + 2)}
        self.assertEqual(found["Buses"], ["Drums", "Cymbals"])
        self.assertEqual(channels(out)[384].label, "Output 1-2")
        self.assertEqual(validate_project(out), [])


class BookkeepingTest(unittest.TestCase):
    def test_the_sequence_triple_and_index_entry(self):
        out, _ = create_stack(session(), name="Nested Stack", members=[504], track_count=TRACKS)
        recs = list(project_records(out))
        seqs = sequences(recs)
        self.assertEqual([t.seq_id for t in seqs][-3:], [10, 12, 11])   # slot order, then the tail
        big = max((r.raw[HEADER:] for r in recs if r.tag == b"qSvE"), key=len)
        self.assertEqual(len(big), 10 * 80)
        entry = big[-80:]
        self.assertEqual((struct.unpack_from("<I", entry, 16)[0], entry[20],
                          struct.unpack_from("<H", entry, 32)[0]), (508, 11, 56))

    def test_the_count_record(self):
        out, _ = create_stack(session(), name="Nested Stack", members=[504], track_count=TRACKS)
        p = next(r.raw[HEADER:] for r in project_records(out) if r.tag == b"nCuA")
        self.assertEqual((len(p), struct.unpack_from("<H", p, 26)[0], struct.unpack_from("<H", p, 40)[0]),
                         (132 + 13 * 4, 13, 4))

    def test_the_registries(self):
        out, _ = create_stack(session(), name="Nested Stack", members=[504], track_count=TRACKS)
        g = next(r.raw[HEADER:] for r in project_records(out) if r.tag == b"gnoS")
        hits = [s for s in range(0, len(g) - 8, 4) if struct.unpack_from("<II", g, s) == (0x14, 508)]
        self.assertEqual(len(hits), 2)
        self.assertEqual(validate_project(out), [])


class RefusalTest(unittest.TestCase):
    def test_no_members(self):
        with self.assertRaises(ValueError):
            create_stack(session(), name="Empty", members=[], track_count=TRACKS)

    def test_unknown_object(self):
        with self.assertRaises(ValueError):
            create_stack(session(), name="X", members=[9999], track_count=TRACKS)

    def test_a_stack_header(self):
        with self.assertRaises(ValueError):
            create_stack(session(), name="X", members=[192], track_count=TRACKS)

    def test_a_track_already_inside_a_stack(self):
        with self.assertRaises(ValueError):
            create_stack(session(), name="X", members=[88], track_count=TRACKS)

    def test_a_corrupt_stream(self):
        with self.assertRaises(ValueError):
            create_stack(session() + b"\x00" * 5, name="X", members=[504], track_count=TRACKS)
