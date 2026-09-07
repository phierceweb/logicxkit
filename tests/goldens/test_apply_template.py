"""The orchestrator: the plan names every difference with the rule that paired the rows, and
apply runs it as the chain of atomic writers. The real-file golden runs the tracking template
against the sessions staged under resources/ when both are present.

The real-file part of tests/logic/test_apply_template.py; skips without the owner's files."""

import unittest
import _goldens
import _paths
from logicxkit.logic.orchestrators.apply_template import apply_template, plan

TEMPLATE = _goldens.path("tracking-template")
SESSIONS = sorted(p for d in ("legacy", "mixes") for p in (_paths.RESOURCES / d).rglob("*.logicx"))
if _goldens.path("tracked-song"):                      # a session cut from the template, project data only
    SESSIONS.append(_goldens.path("tracked-song"))


@unittest.skipIf(not SESSIONS, "no session staged in the reference store")
@_goldens.needs("tracking-template")
class TrackingTemplateTest(unittest.TestCase):
    """Every session on hand was cut from the template: the plan must be field-only, and
    applying it must leave a valid, consistent file with no plan left."""

    @classmethod
    def setUpClass(cls):
        from logicxkit.logic.services.project import project_metadata
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


if __name__ == "__main__":
    unittest.main()
