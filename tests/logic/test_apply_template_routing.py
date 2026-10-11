"""The apply-template ops that change what a row is wired to or belongs to: input and output
routing (a Logic 11.2 template's index words among them), the returns a template silences, groups,
icons, a flaw the session arrived with, and a channel's strip reference."""

import unittest
from _apply_sessions import ref, routed_session, session, word_routed_template
from _records import chan, env_obj, marker, proj, track, uuid
from logicxkit.logic.orchestrators.apply_template import apply_template, plan
from _data import needs


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


class SharedReferenceTest(unittest.TestCase):
    """Two session channels sharing a strip reference may part ways: the template names one of
    them differently, and the refs op repoints that channel alone."""

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
