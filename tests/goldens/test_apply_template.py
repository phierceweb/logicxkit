"""The orchestrator: the plan names every difference with the rule that paired the rows, and
apply runs it as the chain of atomic writers. The real-file golden runs the tracking template
against the sessions staged under resources/ when both are present.

The real-file part of tests/logic/test_apply_template.py; skips without the owner's files."""

import unittest
import _goldens
from logicxkit.logic.orchestrators.apply_template import apply_template, plan

TEMPLATE = _goldens.path("tracking-template")
SESSIONS = _goldens.sessions()
if _goldens.path("tracked-song"):                      # a session cut from the template, project data only
    SESSIONS.append(_goldens.path("tracked-song"))


@unittest.skipIf(not SESSIONS, "no owner's session on this machine")
@_goldens.needs("tracking-template")
class TrackingTemplateTest(unittest.TestCase):
    """Every session on hand was cut from the template: the plan must be field-only, and
    applying it must leave a valid, consistent file with no plan left."""

    @classmethod
    def setUpClass(cls):
        from logicxkit.logic.services.project.project import project_metadata
        from logicxkit.logicx import project_data
        cls.template = project_data(TEMPLATE)
        cls.template_count = project_metadata(TEMPLATE)["tracks"]
        cls.sessions = [(p, project_data(p), project_metadata(p)["tracks"]) for p in SESSIONS]

    def _lineage(self, data, count):
        from logicxkit.logic.orchestrators.apply_template import lineage_problem
        return lineage_problem(self.template, data, template_count=self.template_count,
                               session_count=count)

    def test_plans_pair_by_object_within_the_lineage(self):
        """Within the lineage every paired row pairs by object id; a session may still want
        template tracks it never had (added since, or cut before they existed)."""
        from logicxkit.logic.orchestrators.apply_template import STRUCTURE
        same = [(p, d, c) for p, d, c in self.sessions if self._lineage(d, c) is None]
        if not same:
            self.skipTest("no same-lineage session in the reference store")
        for path, data, count in same:
            with self.subTest(path.stem):
                ops = plan(self.template, data, template_count=self.template_count,
                           session_count=count)
                self.assertTrue(all(op.rule == "object" for op in ops if op.kind not in STRUCTURE), path)
                self.assertEqual([op.line() for op in ops if op.status == "failed"], [], path)

    def test_a_session_from_another_lineage_is_refused_not_planned(self):
        """The guard, on the projects that would otherwise be rewritten: the legacy song's guitars
        pair with the template's drums on the mixer label alone."""
        other = [(p, d, c) for p, d, c in self.sessions if self._lineage(d, c) is not None]
        self.assertTrue(other, "no cross-lineage session on hand to prove the guard")
        for path, data, count in other:
            with self.subTest(path.stem):
                self.assertIn("not the same lineage", self._lineage(data, count))

    def test_apply_converges_on_one_session(self):
        from _invariants import report
        same = [(p, d, c) for p, d, c in self.sessions if self._lineage(d, c) is None]
        if not same:
            self.skipTest("no same-lineage session in the reference store")
        path, data, count = same[0]
        out, ops, added = apply_template(self.template, data, template_count=self.template_count,
                                         session_count=count)
        self.assertEqual(added, 0)
        self.assertEqual([op.line() for op in ops if op.status == "failed"], [])
        r = report(out, count)
        self.assertEqual((r["validate"], r["bad_object_index"], r["bad_send_flags"]), ([], [], []))
        left = [op for op in plan(self.template, out, template_count=self.template_count, session_count=count)
                if op.status == "planned"]
        self.assertEqual([op.line() for op in left], [])


@_goldens.needs("tracking-template", "tracked-song", "apply-current-mine", "apply-current-logic")
class CurrentTemplateResaveTest(unittest.TestCase):
    """The current template applied onto a tracked song: the write as staged, reproduced from its
    inputs and held to Logic's re-save of it (row list and strip references)."""

    def _facts(self, data, count):
        from logicxkit.logic.services.mixer.chains import channel_references
        from logicxkit.logic.services.arrange.stacks import read_tracks
        from logicxkit.logic.services.stream.validate import validate_project
        self.assertEqual(validate_project(data), [])
        return [[t["name"], t.get("label")] for t in read_tracks(data, count)], channel_references(data)

    def _golden(self, key):
        from logicxkit.logic.services.project.project import project_metadata
        from logicxkit.logicx import project_data
        path = _goldens.path(key)
        return project_data(path), project_metadata(path).get("tracks")

    def test_apply_reproduces_the_staged_write(self):
        template, t_count = self._golden("tracking-template")
        song, s_count = self._golden("tracked-song")
        out, ops, added = apply_template(template, song, template_count=t_count, session_count=s_count)
        self.assertEqual([op.line() for op in ops if op.status == "failed"], [])
        rows, refs = self._facts(out, s_count)
        self.assertEqual(rows, _goldens.fact("apply-current-mine", "rows"))
        self.assertEqual((rows, refs), self._facts(*self._golden("apply-current-mine")))

    def test_logic_kept_every_row_and_reference(self):
        want = _goldens.fact("apply-current-mine", "rows")
        mine = self._facts(*self._golden("apply-current-mine"))
        logic = self._facts(*self._golden("apply-current-logic"))
        self.assertEqual(mine[0], want)
        self.assertEqual(logic, mine)
        self.assertEqual(len(logic[1]), _goldens.fact("apply-current-logic", "references"))
        _, song_refs = self._facts(*self._golden("tracked-song"))
        repointed = sum(1 for k, v in logic[1].items() if song_refs.get(k) != v)
        self.assertEqual(repointed, _goldens.fact("apply-current-logic", "repointed"))
        self.assertGreater(repointed, 0)


if __name__ == "__main__":
    unittest.main()
