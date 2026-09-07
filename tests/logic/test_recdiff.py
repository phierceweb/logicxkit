"""Positional record diff.

Records are aligned by position within their tag/size signature sequence, never keyed by
(tag, owner, key): every `karT` row shares owner 65535 and keys repeat per run, so keying them
that way silently drops most rows and reports that nothing changed.
"""

import tempfile
import unittest
from pathlib import Path

from _records import chan, env_obj, marker, proj, track
from logicxkit.logic.services.recdiff import diff_records, load_project_data, noise_mask


class DiffTest(unittest.TestCase):
    def test_identical_streams(self):
        d = diff_records(proj(track(0, 88)), proj(track(0, 88)))
        self.assertEqual((d.added, d.removed, d.changed, d.same), ([], [], [], 1))

    def test_an_inserted_record_is_added_not_a_cascade_of_changes(self):
        a = proj(track(0, 88), marker(), track(0, 92), track(1, 96))
        b = proj(track(0, 88), marker(), track(0, 92), track(1, 504), track(2, 96))
        d = diff_records(a, b)
        self.assertEqual(len(d.added), 1)
        self.assertEqual(d.added[0].tag, b"karT")
        self.assertEqual(d.removed, [])

    def test_changed_offsets_are_record_relative(self):
        a = proj(chan(0, "Audio 1", fader=90))
        b = proj(chan(0, "Audio 1", fader=99))
        d = diff_records(a, b)
        self.assertEqual([c.offsets for c in d.changed], [[36 + 85, 36 + 119]])

    def test_a_length_change_is_reported(self):
        d = diff_records(proj(env_obj(88, "Kick In")), proj(env_obj(88, "Kick In X")))
        self.assertEqual((d.changed[0].size_a, d.changed[0].size_b),
                         (36 + 463 + 8, 36 + 463 + 10))          # names pad to even length

    def test_mask_hides_noise(self):
        a = proj(chan(0, "Audio 1", fader=90), chan(1, "Audio 2", fader=90))
        b = proj(chan(0, "Audio 1", fader=99), chan(1, "Audio 2", fader=90))
        d = diff_records(a, b, mask={b"OCuA": {36 + 85, 36 + 119}})
        self.assertEqual(d.changed, [])
        self.assertEqual(d.same, 2)


class MaskTest(unittest.TestCase):
    def test_mask_is_the_union_of_offsets_that_moved(self):
        a = proj(chan(0, "Audio 1", fader=90), chan(1, "Audio 2", pan=64))
        b = proj(chan(0, "Audio 1", fader=91), chan(1, "Audio 2", pan=65))
        self.assertEqual(noise_mask(a, b), {b"OCuA": {36 + 85, 36 + 119, 36 + 89}})


class LoadTest(unittest.TestCase):
    def test_bare_file_bundle_and_backup_dir(self):
        data = proj(track(0, 88))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "ProjectData").write_bytes(data)
            self.assertEqual(load_project_data(root / "ProjectData"), data)
            self.assertEqual(load_project_data(root), data)          # a backup NN dir
            alt = root / "Song.logicx/Alternatives/000"
            alt.mkdir(parents=True)
            (alt / "ProjectData").write_bytes(data)
            self.assertEqual(load_project_data(root / "Song.logicx"), data)
