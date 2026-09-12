"""The orchestrator: the plan names every difference with the rule that paired the rows, and
apply runs it as the chain of atomic writers."""

import unittest
from _records import chan, env_obj, marker, proj, track, uuid
from logicxkit.logic.orchestrators.apply_template import KINDS, apply_template, plan
from logicxkit.logic.services.stacks import read_tracks
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
        from logicxkit.logic.services.binding import input_routing
        from logicxkit.logic.services.transplant import channel_slots
        template, target = self._session(orphan_slot=False), self._session()
        ops = plan(template, target, template_count=3, session_count=3)
        returns = [op for op in ops if op.kind == "return"]
        self.assertEqual([(op.target, op.detail) for op in returns],
                         [("Aux 2", "returns Bus 1 like Drums (Aux 1): no input, 1 slot(s) removed")])
        out, done, _ = apply_template(template, target, template_count=3, session_count=3)
        self.assertEqual({op.kind: op.status for op in done}, {"return": "done"})
        self.assertIsNone(input_routing(out).get(280))
        self.assertEqual(channel_slots(out, 280), [])
        from logicxkit.logic.services.insert import project_records as _recs
        orphan = next(r for r in _recs(out) if r.owner == 280 and r.tag == b"OCuA")
        self.assertEqual(orphan.raw[36 + 94:36 + 96], b"\xff\xff")

    def test_a_mixer_only_aux_on_the_same_instrument_output_is_unbound(self):
        from _records import rec
        from logicxkit.logic.services.instout import bind_instrument_output, read_instrument_outputs
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
        from logicxkit.logic.services.binding import input_routing
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
        from logicxkit.logic.services.groups import create_group
        base = proj(gnos(88, 504, 80), rec(b"rpyH", 0xFFFF, 0xFFFF, bytes(40)),
                    env_obj(88, "Kick In"), env_obj(504, "Vox"), env_obj(80, "Master", grouping=True),
                    chan(0, "Audio 1", uuid=uuid(88), fader=99), chan(19, "Audio 20", uuid=uuid(504)),
                    chan(402, "Output 1-2", uuid=uuid(80), size=201),
                    track(0, 88), track(1, 504), track(2, 80, flag=3), marker())
        return base, create_group(base, name="Drums", members=[88], settings=["Volume", "Solo"])[0]

    def test_a_template_group_is_made_and_joined(self):
        from logicxkit.logic.services.groups import read_groups
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
        from logicxkit.logic.services.groups import group_of
        plain, grouped = self._grouped()
        ops = plan(plain, grouped, template_count=2, session_count=2)
        self.assertEqual([(op.kind, op.detail) for op in ops], [("group", "leave group Drums")])
        out, done, _ = apply_template(plain, grouped, template_count=2, session_count=2)
        self.assertEqual([op.status for op in done], ["done"])
        self.assertEqual(group_of(out), {})


class IconTest(unittest.TestCase):
    def test_an_icon_difference_becomes_an_op_and_applies(self):
        from logicxkit.logic.services.environment import set_icon
        from logicxkit.logic.services.stacks import read_tracks as rows_of
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
        from logicxkit.logic.services.validate import require_valid, validate_project

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


if __name__ == "__main__":
    unittest.main()
