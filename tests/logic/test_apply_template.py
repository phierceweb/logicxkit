"""The orchestrator: the plan names every difference with the rule that paired the rows, and
apply runs it as the chain of atomic writers."""

import struct
import unittest
from _records import chan, count_record, env_obj, marker, proj, track, uuid
from logicxkit.logic.orchestrators.apply_template import KINDS, apply_template, plan
from logicxkit.logic.services.arrange.stacks import read_tracks
from _data import needs


def session(*, kick_colour=96, kick_fader=99, vox_name="Vox"):
    obj = bytearray(env_obj(88, "Kick In"))
    obj[36 + 155] = kick_colour
    vox = env_obj(504, vox_name)
    return proj(bytes(obj), vox, env_obj(80, "Master", grouping=True),
                chan(0, "Audio 1", uuid=uuid(88), fader=kick_fader),
                chan(19, "Audio 20", uuid=uuid(504)),
                chan(402, "Output 1-2", uuid=uuid(80), size=201),
                track(0, 88), track(1, 504), track(2, 80, flag=3), marker())


class PlanTest(unittest.TestCase):
    def test_no_difference_no_ops(self):
        self.assertEqual(plan(session(), session(), template_count=2, session_count=2), [])

    def test_field_differences_become_ops_with_their_rule(self):
        ops = plan(session(), session(kick_colour=64, kick_fader=80, vox_name="Vocal"),
                   template_count=2, session_count=2)
        self.assertEqual([(op.kind, op.target, op.rule) for op in ops],
                         [("colour", "Kick In (Audio 1)", "object"), ("rename", "Vocal (Audio 20)", "object"),
                          ("levels", "Kick In (Audio 1)", "object")])
        self.assertEqual(ops[1].args, {"track": 504, "name": "Vox"})

    def test_skip_marks_ops_without_dropping_them(self):
        ops = plan(session(), session(kick_fader=80), template_count=2, session_count=2, skip=("levels",))
        self.assertEqual([(op.kind, op.status) for op in ops], [("levels", "skipped")])

    def test_every_kind_is_known(self):
        self.assertEqual(len(set(KINDS)), len(KINDS))


def routed_session() -> bytes:
    """Kick In from Input 1 and Vox from Input 2, both to Output 1-2, by uuid."""
    return proj(env_obj(88, "Kick In"), env_obj(504, "Vox"), env_obj(80, "Master", grouping=True),
                chan(0, "Audio 1", uuid=uuid(88), dest=uuid(80), source=uuid(601)),
                chan(19, "Audio 20", uuid=uuid(504), dest=uuid(80), source=uuid(602)),
                chan(256, "Input 1", uuid=uuid(601), size=201),
                chan(257, "Input 2", uuid=uuid(602), size=201),
                chan(258, "Input 3", uuid=uuid(603), size=201),
                chan(402, "Output 1-2", uuid=uuid(80), size=201),
                track(0, 88), track(1, 504), track(2, 80, flag=3), marker())


def word_routed_template(*, kick_input: int = 0, fmt: int = 2511) -> bytes:
    """The same rows as Logic 11.2 saves them: class-6 channels routed by index words."""
    data = bytearray(proj(
        count_record(1, [0, 0, 0, 0, 32], 1),
        env_obj(88, "Kick In", type_value=1760), env_obj(504, "Vox", type_value=1760),
        env_obj(80, "Master", grouping=True, type_value=1760),
        chan(0, "Audio 1", uuid=uuid(88), size=233, ver=6, words=(0, kick_input)),
        chan(19, "Audio 20", uuid=uuid(504), size=233, ver=6, words=(0, 1)),
        chan(402, "Output 1-2", uuid=uuid(80), size=233, ver=6),
        track(0, 88), track(1, 504), track(2, 80, flag=3), marker()))
    struct.pack_into("<H", data, 4, fmt)
    return bytes(data)


class WordRoutedTemplateTest(unittest.TestCase):
    """A Logic 11.2 template routes by index words: read, they are compared like any other
    routing; not read, they plan nothing — never `-> no input`."""

    def _routing_ops(self, template: bytes) -> list[tuple[str, str, str]]:
        ops = plan(template, routed_session(), template_count=2, session_count=2)
        return [(op.kind, op.target, op.detail) for op in ops if op.kind in ("input", "output")]

    def test_the_same_routing_plans_nothing(self):
        self.assertEqual(self._routing_ops(word_routed_template()), [])

    def test_a_different_input_is_planned_by_its_label(self):
        ops = plan(word_routed_template(kick_input=2), routed_session(), template_count=2,
                   session_count=2)
        (op,) = [op for op in ops if op.kind == "input"]
        self.assertEqual((op.target, op.detail, op.args),
                         ("Kick In (Audio 1)", "-> Input 3", {"owner": 0, "dest": 258}))

    def test_routing_that_is_not_read_plans_nothing(self):
        self.assertEqual(self._routing_ops(word_routed_template(fmt=2510)), [])


class FilterTest(unittest.TestCase):
    def test_only_keeps_the_named_rows_ops(self):
        target = session(kick_colour=64, kick_fader=80, vox_name="Vocal")
        ops = plan(session(), target, template_count=2, session_count=2, only={504})
        self.assertEqual([(op.kind, op.target) for op in ops], [("rename", "Vocal (Audio 20)")])
        ops = plan(session(), target, template_count=2, session_count=2, only={88})
        self.assertEqual([op.kind for op in ops], ["colour", "levels"])
        self.assertTrue(all(op.row == 88 for op in ops))

    def test_a_template_channel_without_slots_removes_the_sessions(self):
        from _records import rec
        kick = chan(0, "Audio 1", uuid=uuid(88), fader=99)
        slot = rec(b"UCuA", 0, 4, bytes(7) + bytes(300), 5)             # +6 = 0 = key - base
        with_slot = session().replace(kick, kick + slot)
        with_slot = with_slot[:16] + (len(with_slot) - 24).to_bytes(4, "little") + with_slot[20:]
        ops = plan(session(), with_slot, template_count=2, session_count=2)
        self.assertEqual([(op.kind, op.status, op.args.get("remove")) for op in ops],
                         [("chains", "planned", True)])
        out, done, _added = apply_template(session(), with_slot, template_count=2, session_count=2)
        self.assertEqual([op.status for op in done], ["done"])
        self.assertEqual(plan(session(), out, template_count=2, session_count=2), [])


class LeaveOutTest(unittest.TestCase):
    def test_an_excluded_template_track_is_not_added(self):
        template = session(vox_name="Vox")
        target = proj(env_obj(88, "Kick In"), env_obj(80, "Master", grouping=True),
                      chan(0, "Audio 1", uuid=uuid(88), fader=99),
                      chan(402, "Output 1-2", uuid=uuid(80), size=201),
                      track(0, 88), track(1, 80, flag=3), marker())
        forced = {"Kick In (Audio 1)": "Kick In (Audio 1)"}
        ops = plan(template, target, template_count=2, session_count=1, forced=forced)
        self.assertEqual([op.target for op in ops if op.kind == "add"], ["Vox (Audio 20)"])
        ops = plan(template, target, template_count=2, session_count=1, forced=forced, excluded={"Vox (Audio 20)"})
        self.assertEqual([op.target for op in ops if op.kind == "add"], [])


class ConsecutiveAddsTest(unittest.TestCase):
    """Two new template tracks, one under the other: the second is placed after the first, or they
    land reversed."""

    def _pair(self):
        from test_stack_create import TRACKS, session as full_session
        base = full_session()
        objs = env_obj(600, "Room L") + env_obj(601, "Room R")
        chans = chan(70, "Aux 4", uuid=uuid(600)) + chan(71, "Aux 5", uuid=uuid(601))
        old_tail = track(7, 216) + track(8, 80, flag=3) + marker()
        new_tail = track(7, 216) + track(8, 600) + track(9, 601) + track(10, 80, flag=3) + marker()
        master, inst = env_obj(80, "Master", grouping=True), chan(88, "Inst 4", uuid=uuid(504))
        body = base.replace(old_tail, new_tail).replace(master, master + objs).replace(inst, inst + chans)
        template = body[:16] + (len(body) - 24).to_bytes(4, "little") + body[20:]
        return template, base, TRACKS

    def test_the_second_add_is_anchored_on_the_first(self):
        template, target, n = self._pair()
        ops = plan(template, target, template_count=n + 2, session_count=n)
        self.assertEqual([op.detail for op in ops if op.kind == "add"],
                         ["add aux track after Cymbals", "add aux track after Room L"])

    @needs("logic", "aux-track-12.3.1.json")
    def test_the_rows_land_in_template_order_without_reordering(self):
        template, target, n = self._pair()
        out, ops, added = apply_template(template, target, template_count=n + 2, session_count=n)
        self.assertEqual([(op.kind, op.status) for op in ops if op.kind in ("add", "order")],
                         [("add", "done"), ("add", "done")])
        self.assertEqual([r["name"] for r in read_tracks(out, n + added)][7:],
                         ["Cymbals", "Room L", "Room R", "Master"])


class MapAcrossStacksTest(unittest.TestCase):
    """A map names a stack as 'Name (Sub N)'; a stack the apply makes renumbers the Sub strips
    above its own, and every later round must still pair the row the map named."""

    def test_a_mapped_sub_row_survives_a_stack_made_below_it(self):
        from _records import uuid as uid
        from test_stack_create import TRACKS, session as stacked, sub
        from logicxkit.logic.services.mixer.pairing import row_key
        from logicxkit.logic.services.arrange.stack_create import create_stack
        from logicxkit.logic.services.arrange.stacks import read_stacks
        template, _ = create_stack(stacked(), name="Bounce", members=[504], track_count=TRACKS)
        target = (stacked().replace(sub(379, 1, uuid=uid(192)), sub(379, 2, uuid=uid(192)))
                  .replace(sub(380, 2, uuid=uid(196)), sub(380, 1, uuid=uid(196))))
        s_keys = [row_key(r) for r in read_tracks(target, TRACKS)]
        t_keys = [row_key(r) for r in read_tracks(template, TRACKS + 1) if r["name"] != "Bounce"]
        self.assertIn("Bass (Sub 1)", s_keys)
        out, ops, added = apply_template(template, target, template_count=TRACKS + 1, session_count=TRACKS,
                                         forced=dict(zip(s_keys, t_keys, strict=True)))
        self.assertEqual((added, [op.line() for op in ops if op.status == "failed"]), (1, []))
        self.assertNotIn("Bass (Sub 1)", [row_key(r) for r in read_tracks(out, TRACKS + 1)])
        stacks = {s.name: [n for _k, n in s.members] for s in read_stacks(out, TRACKS + 1)}
        self.assertEqual((stacks["Bounce"], stacks["Bass"]), (["Test Bounce"], ["Bass DI"]))


class StackOfAddedTracksTest(unittest.TestCase):
    """A template stack whose members the session lacks: the adds are planned, so the plan says
    the stack is made of them. The run adds first and stacks in the next round."""

    def _pair(self):
        from test_stack_create import TRACKS, session as stacked
        from logicxkit.logic.services.arrange.addtrack import add_track
        from logicxkit.logic.services.arrange.stack_create import create_stack
        base = stacked()
        template, r = add_track(base, name="Room", after=504, kind="aux", track_count=TRACKS)
        template, _ = create_stack(template, name="Rooms", members=[r["object_id"]], track_count=TRACKS + 1)
        return template, base, TRACKS

    def test_the_plan_makes_the_stack_of_the_tracks_it_adds(self):
        template, base, n = self._pair()
        ops = [op for op in plan(template, base, template_count=n + 2, session_count=n)
               if op.kind in ("add", "stack")]
        self.assertEqual([(op.kind, op.status) for op in ops], [("stack", "planned"), ("add", "planned")])
        self.assertEqual((ops[0].detail, ops[0].note), ("make a stack of 1 track(s)", "1 of them added above"))
        self.assertTrue(ops[1].detail.startswith("add aux track after Test Bounce"), ops[1].detail)

    def test_the_run_adds_then_stacks(self):
        from logicxkit.logic.services.arrange.stacks import read_stacks
        template, base, n = self._pair()
        out, ops, added = apply_template(template, base, template_count=n + 2, session_count=n)
        self.assertEqual([(op.kind, op.status) for op in ops if op.kind in ("add", "stack")],
                         [("add", "done"), ("stack", "done")])
        stacks = {s.name: [name for _k, name in s.members] for s in read_stacks(out, n + added)}
        self.assertEqual(stacks["Rooms"], ["Room"])


class AlternativesCliTest(unittest.TestCase):
    """`apply-template --map` over two alternatives: the map is drafted from the first, so only
    another alternative may be left as it was — and then byte for byte."""

    MAP = ["Bounce (Inst 4) -> Test Bounce (Inst 4)"]

    def setUp(self):
        import shutil
        import tempfile
        from pathlib import Path
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def run_cli(self, first: bytes, second: bytes) -> tuple[int, str]:
        import contextlib
        import io
        from argparse import Namespace
        from test_migrate import SYNTHETIC_SKIP, alternative, bundle, map_text, other_lineage, session as song_data
        from logicxkit.logic._apply_template import cmd_apply_template
        song = alternative(bundle(self.tmp / "s", "Song", first), "001", second)
        (self.tmp / "map.txt").write_text(map_text(other_lineage(), self.MAP))
        args = Namespace(template=str(bundle(self.tmp / "t", "Tmpl", song_data())), project=str(song),
                         out=str(self.tmp / "out"), plan=False, keep_levels=False, skip=SYNTHETIC_SKIP,
                         track=None, stack=None, propose_map=None, map=str(self.tmp / "map.txt"), force=False)
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            return cmd_apply_template(args), buf.getvalue()

    def test_a_map_the_first_alternative_does_not_fit_is_refused(self):
        from test_migrate import other_lineage, session as song_data
        with self.assertRaisesRegex(ValueError, "map names a session track that does not exist"):
            self.run_cli(song_data({"Test Bounce": "Other"}, shift=1000), other_lineage())
        self.assertEqual(list((self.tmp / "out").rglob("*.logicx")), [])

    def test_another_alternative_the_map_misses_is_left_byte_for_byte(self):
        from unittest import mock
        from test_migrate import other_lineage, session as song_data
        other = song_data({"Test Bounce": "Other"}, shift=1000)
        with mock.patch("logicxkit.logic._apply_template._rebased", lambda d: d.replace(b"Other", b"Otter")):
            rc, text = self.run_cli(other_lineage(), other)
        self.assertEqual(rc, 0, text)
        self.assertIn("001: left as it was", text)
        self.assertEqual((self.tmp / "out/Song.logicx/Alternatives/001/ProjectData").read_bytes(), other)


class SessionOnlyTest(unittest.TestCase):
    def test_rows_the_template_lacks_are_named(self):
        from logicxkit.logic.orchestrators.apply_template import session_only
        template = session()
        target = proj(env_obj(88, "Kick In"), env_obj(504, "Vox"), env_obj(700, "Room"),
                      env_obj(80, "Master", grouping=True),
                      chan(0, "Audio 1", uuid=uuid(88), fader=99), chan(19, "Audio 20", uuid=uuid(504)),
                      chan(20, "Audio 21", uuid=uuid(700)),
                      chan(402, "Output 1-2", uuid=uuid(80), size=201),
                      track(0, 88), track(1, 504), track(2, 700), track(3, 80, flag=3), marker())
        rows = session_only(template, target, template_count=2, session_count=3)
        self.assertEqual([r["name"] for r in rows], ["Room"])


class ReturnsTest(unittest.TestCase):
    """A legacy song returns its buses through mixer-only auxes; once a template aux track
    returns the same bus the old return is silenced, or the bus plays twice."""

    def _session(self, orphan_slot=True):
        from _records import rec
        bus = chan(300, "Bus 1", uuid=uuid(700), size=201)
        ret = env_obj(96, "Drums")                                  # the template-style return, a track
        orphan = chan(280, "Aux 2", uuid=uuid(701), source=uuid(700))
        slot = bytes(500)                                          # +6 = 0: slot index 0 at key 4
        parts = [env_obj(88, "Kick In"), ret, env_obj(80, "Master", grouping=True),
                 chan(0, "Audio 1", uuid=uuid(88), fader=99), bus,
                 chan(270, "Aux 1", uuid=uuid(96), source=uuid(700)), orphan]
        if orphan_slot:
            parts.append(rec(b"UCuA", 280, 4, bytes(slot), 5))
        parts += [chan(402, "Output 1-2", uuid=uuid(80), size=201),
                  track(0, 88), track(1, 96), track(2, 80, flag=3), marker()]
        return proj(*parts)

    def test_the_old_return_is_silenced(self):
        from logicxkit.logic.services.mixer.binding import input_routing
        from logicxkit.logic.services.mixer.transplant import channel_slots
        template, target = self._session(orphan_slot=False), self._session()
        ops = plan(template, target, template_count=3, session_count=3)
        returns = [op for op in ops if op.kind == "return"]
        self.assertEqual([(op.target, op.detail) for op in returns],
                         [("Aux 2", "returns Bus 1 like Drums (Aux 1): no input, 1 slot(s) removed")])
        out, done, _ = apply_template(template, target, template_count=3, session_count=3)
        self.assertEqual({op.kind: op.status for op in done}, {"return": "done"})
        self.assertIsNone(input_routing(out).get(280))
        self.assertEqual(channel_slots(out, 280), [])
        from logicxkit.logic.services.stream.stream import project_records as _recs
        orphan = next(r for r in _recs(out) if r.owner == 280 and r.tag == b"OCuA")
        self.assertEqual(orphan.raw[36 + 94:36 + 96], b"\xff\xff")

    def test_a_mixer_only_aux_on_the_same_instrument_output_is_unbound(self):
        from _records import rec
        from logicxkit.logic.services.mixer.instout import bind_instrument_output, read_instrument_outputs
        def project(orphan_bound):
            parts = [env_obj(88, "Drums MIDI"), env_obj(96, "OH MIDI"), env_obj(80, "Master", grouping=True),
                     chan(86, "Inst 2", uuid=uuid(88)), rec(b"UCuA", 86, 13, bytes(192), 5),
                     chan(67, "Aux 1", uuid=uuid(96)), rec(b"UCuA", 67, 13, bytes(192), 5),
                     chan(68, "Aux 2", uuid=uuid(700)), rec(b"UCuA", 68, 13, bytes(192), 5),
                     chan(402, "Output 1-2", uuid=uuid(80), size=201),
                     track(0, 88), track(1, 96), track(2, 80, flag=3), marker()]
            data = proj(*parts)
            import test_instout
            data = bind_instrument_output(data, 67, pattern=test_instout.pattern(), instrument=2)
            if orphan_bound:
                data = bind_instrument_output(data, 68, pattern=test_instout.pattern(), instrument=2)
            return data
        template, target = project(False), project(True)
        ops = plan(template, target, template_count=3, session_count=3)
        self.assertEqual([(op.kind, op.target, op.detail) for op in ops],
                         [("return", "Aux 2", "takes Addictive 13-14 of Inst 2 like OH MIDI (Aux 1): unbound")])
        out, done, _ = apply_template(template, target, template_count=3, session_count=3)
        self.assertEqual([op.status for op in done], ["done"])
        self.assertEqual(list(read_instrument_outputs(out)), [67])

    def test_a_track_the_template_feeds_from_nothing_loses_its_input(self):
        from logicxkit.logic.services.mixer.binding import input_routing
        fed = proj(env_obj(88, "Kick In"), env_obj(80, "Master", grouping=True),
                   chan(0, "Audio 1", uuid=uuid(88), fader=99, source=uuid(500)),
                   chan(256, "Input 1", uuid=uuid(500), size=201),
                   chan(402, "Output 1-2", uuid=uuid(80), size=201),
                   track(0, 88), track(1, 80, flag=3), marker())
        unfed = fed.replace(uuid(500), bytes(16), 1)
        ops = plan(unfed, fed, template_count=2, session_count=2)
        self.assertEqual([(op.kind, op.detail) for op in ops], [("input", "-> no input")])
        out, done, _ = apply_template(unfed, fed, template_count=2, session_count=2)
        self.assertEqual([op.status for op in done], ["done"])
        self.assertIsNone(input_routing(out)[0])


@needs("logic", "group-12.3.1.json")
class GroupOpTest(unittest.TestCase):
    """The template's groups, by name: made in the session when missing, and paired rows
    put in them; a row grouped where its template row is not leaves its group."""

    def _grouped(self):
        from _records import gnos, rec
        from logicxkit.logic.services.arrange.groups import create_group
        base = proj(gnos(88, 504, 80), rec(b"rpyH", 0xFFFF, 0xFFFF, bytes(40)),
                    env_obj(88, "Kick In"), env_obj(504, "Vox"), env_obj(80, "Master", grouping=True),
                    chan(0, "Audio 1", uuid=uuid(88), fader=99), chan(19, "Audio 20", uuid=uuid(504)),
                    chan(402, "Output 1-2", uuid=uuid(80), size=201),
                    track(0, 88), track(1, 504), track(2, 80, flag=3), marker())
        return base, create_group(base, name="Drums", members=[88], settings=["Volume", "Solo"])[0]

    def test_a_template_group_is_made_and_joined(self):
        from logicxkit.logic.services.arrange.groups import read_groups
        plain, grouped = self._grouped()
        ops = plan(grouped, plain, template_count=2, session_count=2)
        self.assertEqual([(op.kind, op.target, op.detail) for op in ops],
                         [("group", "Kick In (Audio 1)", "-> group Drums (Volume, Solo)")])
        out, done, _ = apply_template(grouped, plain, template_count=2, session_count=2)
        self.assertEqual([op.status for op in done], ["done"])
        g = read_groups(out)
        self.assertEqual([(x.name, x.members, x.settings) for x in g], [("Drums", (88,), ["Volume", "Solo"])])
        self.assertEqual(plan(grouped, out, template_count=2, session_count=2), [])

    def test_a_row_the_template_has_in_no_group_leaves_its_group(self):
        from logicxkit.logic.services.arrange.groups import group_of
        plain, grouped = self._grouped()
        ops = plan(plain, grouped, template_count=2, session_count=2)
        self.assertEqual([(op.kind, op.detail) for op in ops], [("group", "leave group Drums")])
        out, done, _ = apply_template(plain, grouped, template_count=2, session_count=2)
        self.assertEqual([op.status for op in done], ["done"])
        self.assertEqual(group_of(out), {})


class IconTest(unittest.TestCase):
    def test_an_icon_difference_becomes_an_op_and_applies(self):
        from logicxkit.logic.services.arrange.environment import set_icon
        from logicxkit.logic.services.arrange.stacks import read_tracks as rows_of
        template, target = set_icon(session(), 88, 0x1234), session()
        ops = plan(template, target, template_count=2, session_count=2)
        self.assertEqual([(op.kind, op.detail) for op in ops], [("icon", "0 -> 4660")])
        out, done, _ = apply_template(template, target, template_count=2, session_count=2)
        self.assertEqual([op.status for op in done], ["done"])
        self.assertEqual({r["name"]: r["icon"] for r in rows_of(out, 2)}["Kick In"], 0x1234)


class ToleratedFlawTest(unittest.TestCase):
    def test_a_flaw_the_session_arrived_with_does_not_block_the_edits(self):
        """Two slots claiming one index fail the validator; an old session that already has
        that must still take a colour change, and the flaw must not grow."""
        from _fixtures import chunk
        from _records import rec
        from logicxkit.logic.services.stream.validate import require_valid, validate_project

        def slot(key):
            p = bytearray(600)
            p[6] = 0                                       # both say index 0
            body = chunk(154, [0.0] * 4)
            p[300:300 + len(body)] = body
            return rec(b"UCuA", 0, key, bytes(p), 5)
        kick = chan(0, "Audio 1", uuid=uuid(88), fader=99)
        target = session(kick_colour=64).replace(kick, kick + slot(4) + slot(5))
        target = target[:16] + (len(target) - 24).to_bytes(4, "little") + target[20:]
        flaws = validate_project(target)
        self.assertTrue(any("colliding" in f for f in flaws), flaws)
        with self.assertRaises(ValueError):
            require_valid(target)
        out, ops, _ = apply_template(session(), target, template_count=2, session_count=2)
        self.assertEqual([(op.kind, op.status) for op in ops if op.kind == "colour"], [("colour", "done")])
        self.assertLessEqual(set(validate_project(out)), set(flaws))     # no new flaw; the old may go


class ApplyTest(unittest.TestCase):
    def test_apply_runs_the_field_ops(self):
        template, target = session(), session(kick_colour=64, kick_fader=80, vox_name="Vocal")
        out, ops, added = apply_template(template, target, template_count=2, session_count=2)
        self.assertEqual([op.status for op in ops], ["done", "done", "done"])
        self.assertEqual(added, 0)
        rows = {r["name"]: r for r in read_tracks(out, 2)}
        self.assertEqual((rows["Kick In"]["colour"], "Vox" in rows), (96, True))
        self.assertEqual(plan(template, out, template_count=2, session_count=2), [])


def ref(owner: int, name: str, category: str = "Guitar") -> bytes:
    """A channel's strip-reference record: the name and category fields a `.cst` reference holds."""
    from _records import rec
    return rec(b"UCuA", owner, 10, b"\x00" * 16 + name.encode().ljust(64, b"\x00") + category.encode().ljust(64, b"\x00"))


class SharedReferenceTest(unittest.TestCase):
    """Two session channels sharing a strip reference may part ways: the template names one of
    them differently, and the refs op repoints that channel alone (the current tracking template
    does exactly this to a session cut from its predecessor, 2026-09-16)."""

    @staticmethod
    def _project(ref_a: str, ref_b: str) -> bytes:
        return proj(env_obj(88, "Gtr 1"), env_obj(92, "Gtr 2"), env_obj(80, "Master", grouping=True),
                    chan(0, "Audio 1", uuid=uuid(88)), ref(0, ref_a),
                    chan(1, "Audio 2", uuid=uuid(92)), ref(1, ref_b),
                    chan(402, "Output 1-2", uuid=uuid(80), size=201),
                    track(0, 88), track(1, 92), track(2, 80, flag=3), marker())

    def test_a_reference_the_template_lacks_is_named_and_left(self):
        template = proj(env_obj(88, "Gtr 1"), env_obj(80, "Master", grouping=True),
                        chan(0, "Audio 1", uuid=uuid(88)),
                        chan(402, "Output 1-2", uuid=uuid(80), size=201), track(0, 88), track(1, 80, flag=3), marker())
        session = proj(env_obj(88, "Gtr 1"), env_obj(80, "Master", grouping=True),
                       chan(0, "Audio 1", uuid=uuid(88)), ref(0, "Guitar SLO.cst"),
                       chan(402, "Output 1-2", uuid=uuid(80), size=201), track(0, 88), track(1, 80, flag=3), marker())
        ops = [op for op in plan(template, session, template_count=1, session_count=1) if op.kind == "refs"]
        self.assertEqual([(op.status, op.detail) for op in ops], [("refused", "carries Guitar SLO.cst; the template has none")])

    def test_one_of_two_channels_sharing_a_reference_is_repointed_alone(self):
        template = self._project("Guitar SLO.cst", "Guitar SLO M.cst")
        target = self._project("Guitar SLO.cst", "Guitar SLO.cst")
        out, ops, _added = apply_template(template, target, template_count=2, session_count=2)
        refs = [(op.args.get("owner"), op.status) for op in ops if op.kind == "refs"]
        self.assertEqual(refs, [(1, "done")])
        self.assertEqual(plan(template, out, template_count=2, session_count=2), [])


if __name__ == "__main__":
    unittest.main()
