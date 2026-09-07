"""One document for a project's template-level shape, built only from decoded fields.

The real-file part of tests/logic/test_manifest.py; skips without the owner's files."""

import unittest
import _goldens



TEMPLATE = _goldens.path("tracking-template")


@_goldens.needs("tracking-template")
class GoldenManifestTest(unittest.TestCase):
    def test_template_manifest_is_internally_consistent(self):
        from logicxkit.logic.services.manifest import read_manifest
        from logicxkit.logic.services.binding import channels
        from logicxkit.logicx import project_data
        m = read_manifest(TEMPLATE)
        self.assertEqual(len(m["tracks"]), m["metadata"]["tracks"] + 1)
        self.assertEqual(len(m["stacks"]), _goldens.fact("tracking-template", "stacks", 7))
        # destinations are bus stubs, which are not in use and so not manifest rows
        labels = {c.label for c in channels(project_data(TEMPLATE)).values()}
        for c in m["channels"]:
            if c["output"] is not None:
                self.assertIn(c["output"], labels)
            for s in c["sends"]:
                self.assertIsNotNone(s["to"])


if __name__ == "__main__":
    unittest.main()
