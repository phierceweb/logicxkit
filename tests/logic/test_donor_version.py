"""Retargeting a slot record between class versions.

No v3 project on disk contains a native algorithmic reverb, so the three v3 sessions could not
be given one. The v3/v5 schema delta was measured by diffing the library's own pairs — Channel
EQ, Compressor, Echo and Klopfgeist, four plugins of very different sizes — and is three
things: a payload-header constant, the plugin-variant id, and four trailing bytes.
"""

import struct
import unittest

from logicxkit.utils.data import data_dir

from logicxkit.logic._binary import find_blocks
from logicxkit.logic.services.donors import (
    SCHEMA_CONST,
    VARIANT_AT,
    donor_key,
    load_donor_library,
    retarget_version,
)

HDR = 36

LIBRARY = data_dir("donors")


def _lib():
    if not LIBRARY.exists():
        raise unittest.SkipTest("donor library not present")
    return {k: (v[0] if isinstance(v, tuple) else v) for k, v in
            load_donor_library(LIBRARY).items()}


class RetargetVersionTest(unittest.TestCase):
    PAIRS = (236, 154, 147)   # pairs whose float count is unchanged across versions

    def test_downgrading_v5_reproduces_the_real_v3_record(self):
        """The proof: for every plugin with both versions, the derived v3 record differs from
        the real one only in bytes that are per-donor content, never in structure."""
        lib = _lib()
        for tid in self.PAIRS:
            with self.subTest(plugin=tid):
                real3, real5 = lib[donor_key(tid, 3)], lib[donor_key(tid, 5)]
                made = retarget_version(real5, 3)
                self.assertEqual(len(made), len(real3), "length must match exactly")
                blocks = find_blocks(real3[HDR:])
                label_end = HDR + blocks[0][0] - 12
                structural = [i for i in range(len(real3))
                              if made[i] != real3[i] and i >= HDR and i >= label_end]
                self.assertEqual(structural, [], "no unexplained structural difference")

    def test_the_three_changed_fields(self):
        lib = _lib()
        made = retarget_version(lib[donor_key(236, 5)], 3)
        self.assertEqual(struct.unpack_from("<H", made, 4)[0], 3)
        self.assertEqual(struct.unpack_from("<I", made, HDR)[0], SCHEMA_CONST[3])
        self.assertEqual(struct.unpack_from("<H", made, HDR + VARIANT_AT)[0], 0)

    def test_the_records_own_size_field_follows_the_new_length(self):
        lib = _lib()
        made = retarget_version(lib[donor_key(154, 5)], 3)
        self.assertEqual(struct.unpack_from("<I", made, 28)[0], len(made) - HDR)

    def test_the_parameter_floats_survive_untouched(self):
        lib = _lib()
        for tid in self.PAIRS:
            with self.subTest(plugin=tid):
                src = lib[donor_key(tid, 5)]
                made = retarget_version(src, 3)
                a, b = find_blocks(src[HDR:])[0], find_blocks(made[HDR:])[0]
                self.assertEqual(b[1], a[1], "same plugin type")
                self.assertEqual(b[2], a[2], "same float count")
                self.assertEqual(made[HDR + b[0]:HDR + b[0] + 12 + b[2] * 4],
                                 src[HDR + a[0]:HDR + a[0] + 12 + a[2] * 4])

    def test_a_plugin_whose_float_count_changed_is_refused(self):
        """Klopfgeist gained a parameter between versions (14 -> 15 floats) and has no trailer,
        so its 4-byte delta is a PARAMETER, not schema slack. Deriving would truncate it."""
        lib = _lib()
        with self.assertRaises(ValueError) as caught:
            retarget_version(lib[donor_key(158, 5)], 3)
        self.assertIn("float count differs", str(caught.exception))

    def test_the_reverbs_are_in_the_derivable_family(self):
        """ChromaVerb / SilverVerb / EnVerb all carry a 20-byte trailer like Compressor and
        Echo, so the transform applies — but no v3 counterpart exists to confirm it."""
        lib = _lib()
        for tid in (287, 150, 166):
            with self.subTest(plugin=tid):
                made = retarget_version(lib[donor_key(tid, 5)], 3)
                a = find_blocks(lib[donor_key(tid, 5)][HDR:])[0]
                b = find_blocks(made[HDR:])[0]
                self.assertEqual(b[2], a[2], "parameter count preserved")

    def test_upgrading_is_refused_because_the_variant_id_cannot_be_invented(self):
        lib = _lib()
        with self.assertRaises(ValueError):
            retarget_version(lib[donor_key(236, 3)], 5)

    def test_same_version_is_a_no_op(self):
        lib = _lib()
        raw = lib[donor_key(236, 5)]
        self.assertIs(retarget_version(raw, 5), raw)


if __name__ == "__main__":
    unittest.main()
