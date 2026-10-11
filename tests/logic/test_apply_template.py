"""The orchestrator: the plan names every difference with the rule that paired the rows, and
apply runs it as the chain of atomic writers — the plan's shape, its filters, the tracks it adds
and stacks, and the command over alternatives. Routing, returns, groups, icons, flaws and strip
references are in `test_apply_template_routing.py`."""

import unittest
from _apply_sessions import session
from _records import chan, env_obj, marker, proj, track, uuid
from logicxkit.logic.orchestrators.apply_template import KINDS, apply_template, plan
from logicxkit.logic.services.arrange.stacks import read_tracks
from _data import needs


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
