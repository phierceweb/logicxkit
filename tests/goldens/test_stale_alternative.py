"""A bundle holding an alternative an earlier Logic saved beside a current one: a writer edits
the current one and leaves the other byte for byte, and Logic 12.4 opened both and saved the
bundle with the older one still as it was. Skips without the owner's files."""

import unittest

import _goldens
from logicxkit.logic.services.arrange.retrack import stale_alternatives
from logicxkit.logic.services.mixer.levels import read_levels

BEFORE, OURS, RESAVE = "stale-alt-before", "stale-alt-ours", "stale-alt-resave-logic"


def alternative(key: str, name: str) -> bytes:
    return (_goldens.path(key) / "Alternatives" / name / "ProjectData").read_bytes()


@_goldens.needs(BEFORE, OURS, RESAVE)
class StaleAlternativeTest(unittest.TestCase):
    def test_each_bundle_keeps_the_older_alternative_beside_the_current_one(self):
        for key in (BEFORE, OURS, RESAVE):
            with self.subTest(key):
                self.assertEqual(stale_alternatives(_goldens.path(key)), _goldens.fact(key, "stale"))

    def test_the_write_and_logics_save_left_the_older_alternative_byte_for_byte(self):
        (older,) = _goldens.fact(BEFORE, "stale")
        self.assertEqual(alternative(OURS, older), alternative(BEFORE, older))
        self.assertEqual(alternative(RESAVE, older), alternative(BEFORE, older))

    def test_logic_kept_the_fader_written_on_the_current_alternative(self):
        current = _goldens.fact(OURS, "current")
        was, ours, logics = (read_levels(alternative(k, current))[0]["fader_fixed"] for k in (BEFORE, OURS, RESAVE))
        self.assertEqual((ours, logics), (_goldens.fact(OURS, "audio_1_fixed"),) * 2)
        self.assertNotEqual(was, ours)


if __name__ == "__main__":
    unittest.main()
