"""The packaged templates are exactly the records Logic wrote in the public saves."""

import json
import sys
import unittest
from pathlib import Path

import _goldens

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import regen_data  # noqa: E402


@_goldens.needs("blank-base", "tracks-two-audio-logic")
class ExtractTest(unittest.TestCase):
    def test_the_audio_channel_template_is_logics_new_strip(self):
        t = regen_data.channel(("blank-base", "tracks-two-audio-logic"), "Audio 2")
        self.assertEqual(set(t), {"source", "header", "payload"})
        self.assertEqual(bytes.fromhex(t["header"])[:4], b"OCuA")
        self.assertGreater(len(bytes.fromhex(t["payload"])), 200)      # a mixer record, not a stub


class PackagedMatchesCorpusTest(unittest.TestCase):
    def test_every_packaged_file_matches_a_fresh_extraction(self):
        for name, (keys, make) in regen_data.TEMPLATES.items():
            with self.subTest(name):
                missing = [k for k in keys if _goldens.path(k) is None]
                if missing:
                    self.skipTest(f"golden(s) not on this machine: {', '.join(missing)}")
                packaged = json.loads((regen_data.OUT / "logic" / name).read_text())
                self.assertEqual(packaged, make())


class PackagedDonorsMatchCorpusTest(unittest.TestCase):
    """The packaged donor library is exactly a fresh harvest of `DONOR_KEYS`, manifest included:
    nothing in it the corpus does not hold (a scrubbed save regenerates its donor)."""

    def test_a_fresh_harvest_is_the_packaged_library(self):
        import tempfile
        missing = [k for k, _label in regen_data.DONOR_KEYS if _goldens.path(k) is None]
        if missing:
            self.skipTest(f"golden(s) not on this machine: {', '.join(missing)}")
        packaged = regen_data.OUT / "donors"
        with tempfile.TemporaryDirectory() as tmp:
            fresh = Path(tmp) / "donors"
            regen_data.donors(fresh)
            self.assertEqual(sorted(p.name for p in fresh.iterdir()), sorted(p.name for p in packaged.iterdir()))
            for f in sorted(fresh.iterdir()):
                with self.subTest(f.name):
                    if f.suffix == ".json":
                        self.assertEqual(json.loads(f.read_text()), json.loads((packaged / f.name).read_text()))
                    else:
                        self.assertEqual(f.read_bytes(), (packaged / f.name).read_bytes())


if __name__ == "__main__":
    unittest.main()
