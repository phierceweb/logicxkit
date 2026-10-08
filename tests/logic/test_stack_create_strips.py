"""Creating a folder stack: which `Sub` strip the header binds — the packaged pattern on a
stackless session, a strip out of use taken back, a new one after the highest — and the summing
aux that is never the pattern."""

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
from logicxkit.logic.services.mixer.binding import channels
from logicxkit.logic.services.mixer.levels import read_levels
from logicxkit.logic.services.arrange.environment import channel_objects
from logicxkit.logic.services.stream.stream import HEADER, project_records
from logicxkit.logic.services.arrange.stack_create import SUB_NUMBER_AT, create_stack
from logicxkit.logic.services.arrange.stacks import read_stacks
from logicxkit.logic.services.stream.validate import validate_project
from test_stack_create import MIXER, TRACKS, flat_session, sub


class StacklessSessionTest(unittest.TestCase):
    def test_a_session_with_no_stack_gets_one_from_the_packaged_pattern(self):
        out, report = create_stack(flat_session(), name="Drums", members=[88, 92], track_count=3)
        (stack,) = read_stacks(out, 4)
        self.assertEqual((stack.name, stack.kind, [n for _k, n in stack.members]),
                         ("Drums", "folder", ["Kick", "Snare"]))
        self.assertEqual(validate_project(out), [])

    def test_the_sub_strip_lands_after_the_master_strip(self):
        out, report = create_stack(flat_session(), name="Drums", members=[88, 92], track_count=3)
        labels = {o: c.label for o, c in channels(out).items()}
        self.assertEqual(report["label"], "Sub 1")
        self.assertEqual([labels[o] for o in sorted(labels) if o >= 400],
                         ["Master", "Sub 1", "Input 1-2", "Output 1-2"])


def session_with_sub_above(in_use: bool = True) -> bytes:
    """``session()`` plus an unbound `Sub 4` strip after Sub 2: in use, as a flattened stack
    leaves one, or out of use, as a converted one does."""
    table = b"".join(index_entry(oid, 2 + k, 20 + 4 * k) for k, oid in enumerate(MIXER))
    return proj(
        count_record(13, [6, 0, 2, 1, 1, 0, 4], 13),
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
        sub(379, 1, uuid=uuid(192)), sub(380, 2, uuid=uuid(196)), sub(381, 4, uuid=uuid(900), in_use=in_use),
        chan(382, "Input 1-2", size=201, in_use=False),
        chan(383, "Output 1-2", uuid=uuid(80), size=201), send(383, 0, 5),
        seq_triple(1, big=table),
        track(0, 192), track(1, 88, member=True), track(2, 92, member=True), track(3, 196),
        track(4, 152, member=True), track(5, 504), track(6, 212), track(7, 216),
        track(8, 80, flag=3), marker(),
        *(track(k, oid) for k, oid in enumerate([296, 300, 304] + MIXER)), marker(),
        *(seq_triple(2 + k, slot=20 + 4 * k, object_id=oid, index=2 + k)
          for k, oid in enumerate(MIXER)),
        seq_triple(11, slot=100, size=341))


class SubStripsBesideTheStacksTest(unittest.TestCase):
    """Which `Sub` strip a new folder takes when one sits above the folder stacks: a new one
    after the highest while that one is in use, the strip itself when it is out of use."""

    def test_a_new_strip_goes_after_a_higher_sub_that_is_in_use(self):
        out, report = create_stack(session_with_sub_above(), name="Nested Stack", members=[504],
                                   track_count=TRACKS)
        self.assertEqual((report["label"], report["owner"]), ("Sub 5", 382))
        strip = next(r.raw[HEADER:] for r in project_records(out) if r.tag == b"OCuA" and r.owner == 382)
        self.assertEqual((channels(out)[382].label, strip[SUB_NUMBER_AT]), ("Sub 5", 5))
        self.assertEqual([c.label for o, c in sorted(channels(out).items()) if c.label.startswith("Sub ")],
                         ["Sub 1", "Sub 2", "Sub 4", "Sub 5"])
        self.assertEqual(validate_project(out), [])

    def test_a_sub_out_of_use_is_taken_and_no_channel_moves(self):
        data = session_with_sub_above(in_use=False)
        out, report = create_stack(data, name="Nested Stack", members=[504], track_count=TRACKS)
        self.assertEqual((report["label"], report["owner"]), ("Sub 4", 381))
        self.assertEqual({o: c.label for o, c in channels(out).items()}, {o: c.label for o, c in channels(data).items()})
        self.assertEqual((channels(data)[381].in_use, channels(out)[381].in_use), (False, True))
        header = channel_objects(out)[report["object_id"]]
        self.assertEqual(channels(out)[381].uuid, header.uuid)
        self.assertEqual(validate_project(out), [])

    def test_a_sub_out_of_use_comes_back_at_0_db_and_not_muted(self):
        data = bytearray(session_with_sub_above(in_use=False))
        strip = next(r for r in project_records(bytes(data)) if r.tag == b"OCuA" and r.owner == 381)
        at = bytes(data).index(strip.raw) + HEADER
        data[at + 85] = data[at + 119] = 60                       # its fader, left off unity
        data[at + 90] |= 1                                        # and its mute
        out, report = create_stack(bytes(data), name="Nested Stack", members=[504], track_count=TRACKS)
        level = read_levels(out)[381]
        self.assertEqual((report["label"], level["fader"], level["fader_fixed"], level["mute"]),
                         ("Sub 4", 90, 90 << 24, False))

    def test_a_sub_out_of_use_with_a_pan_or_a_solo_is_refused(self):
        for at, value, what in ((89, 20, "a pan"), (88, 1, "a solo")):
            with self.subTest(what):
                data = bytearray(session_with_sub_above(in_use=False))
                strip = next(r for r in project_records(bytes(data)) if r.tag == b"OCuA" and r.owner == 381)
                data[bytes(data).index(strip.raw) + HEADER + at] = value
                with self.assertRaisesRegex(ValueError, f"Sub 4 is out of use .* {what}"):
                    create_stack(bytes(data), name="Nested Stack", members=[504], track_count=TRACKS)


SUMMING_MIXER = MIXER + [600, 604]


def session_with_summing() -> bytes:
    """``session()`` plus a summing stack Plate(Aux 30){Plate Send} whose Aux number outranks
    every Sub — the pattern for a new folder stack is still the highest Sub."""
    table = b"".join(index_entry(oid, 2 + k, 20 + 4 * k) for k, oid in enumerate(SUMMING_MIXER))
    return proj(
        count_record(14, [6, 0, 4, 1, 1, 0, 3], 14),
        gnos(88, 92, 152, 192, 196, 212, 216, 504, 600, 604),
        env_obj(192, "Drums", grouping=True), env_obj(88, "Kick In"), env_obj(92, "Snare Up"),
        env_obj(196, "Bass", grouping=True), env_obj(152, "Bass DI"),
        env_obj(504, "Test Bounce"), env_obj(212, "Drums"), env_obj(216, "Cymbals"),
        env_obj(600, "Plate", grouping=True), env_obj(604, "Plate Send"),
        env_obj(80, "Master", grouping=True),
        chan(0, "Audio 1", uuid=uuid(88), stack_index=1),
        chan(2, "Audio 3", uuid=uuid(92), stack_index=1),
        chan(16, "Audio 17", uuid=uuid(152), stack_index=2),
        chan(68, "Aux 2", uuid=uuid(212)), chan(69, "Aux 3", uuid=uuid(216)),
        chan(70, "Aux 30", uuid=uuid(600)), chan(71, "Aux 31", uuid=uuid(604)),
        chan(88, "Inst 4", uuid=uuid(504)),
        sub(379, 1, uuid=uuid(192)), sub(380, 2, uuid=uuid(196)),
        chan(381, "Input 1-2", size=201, in_use=False),
        chan(382, "Output 1-2", uuid=uuid(80), size=201), send(382, 0, 5),
        seq_triple(1, big=table),
        track(0, 192), track(1, 88, member=True), track(2, 92, member=True), track(3, 196),
        track(4, 152, member=True), track(5, 504), track(6, 212), track(7, 216),
        track(8, 600), track(9, 604, member=True), track(10, 80, flag=3), marker(),
        *(track(k, oid) for k, oid in enumerate([296, 300, 304] + SUMMING_MIXER)), marker(),
        *(seq_triple(2 + k, slot=20 + 4 * k, object_id=oid, index=2 + k)
          for k, oid in enumerate(SUMMING_MIXER)),
        seq_triple(13, slot=100, size=341))


class SummingStackIsNotThePatternTest(unittest.TestCase):
    def test_the_new_folder_follows_the_highest_sub_not_the_summing_aux(self):
        data = session_with_summing()
        kinds = {s.name: s.kind for s in read_stacks(data, 10)}
        self.assertEqual((kinds["Plate"], kinds["Bass"]), ("summing", "folder"))
        out, report = create_stack(data, name="Nested Stack", members=[504], track_count=10)
        self.assertEqual((report["label"], report["owner"]), ("Sub 3", 381))
        chans = channels(out)
        self.assertEqual([c.label for o, c in sorted(chans.items()) if c.label.startswith(("Sub ", "Aux 3"))],
                         ["Aux 3", "Aux 30", "Aux 31", "Sub 1", "Sub 2", "Sub 3"])
        self.assertEqual(validate_project(out), [])


if __name__ == "__main__":
    unittest.main()
