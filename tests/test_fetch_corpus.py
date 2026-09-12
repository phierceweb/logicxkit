"""`bin/run fetch-corpus`: a downloaded corpus is unpacked only when its checksum matches."""

import hashlib
import io
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import fetch_corpus  # noqa: E402


def _tar(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class UnpackTest(unittest.TestCase):
    def test_a_matching_checksum_unpacks_under_resources(self):
        blob = _tar({"public/a.logicx/Alternatives/000/ProjectData": b"x"})
        with tempfile.TemporaryDirectory() as tmp:
            resources = Path(tmp)
            fetch_corpus.unpack(blob, hashlib.sha256(blob).hexdigest(), resources)
            self.assertEqual((resources / "public/a.logicx/Alternatives/000/ProjectData").read_bytes(), b"x")

    def test_a_wrong_checksum_writes_nothing(self):
        blob = _tar({"public/a.logicx/Alternatives/000/ProjectData": b"x"})
        with tempfile.TemporaryDirectory() as tmp:
            resources = Path(tmp)
            with self.assertRaises(fetch_corpus.CorpusError):
                fetch_corpus.unpack(blob, "0" * 64, resources)
            self.assertFalse((resources / "public").exists())

    def test_a_member_outside_public_is_refused(self):
        blob = _tar({"../escape": b"x"})
        with tempfile.TemporaryDirectory() as tmp:
            resources = Path(tmp)
            with self.assertRaises(fetch_corpus.CorpusError):
                fetch_corpus.unpack(blob, hashlib.sha256(blob).hexdigest(), resources)
            self.assertEqual(list(resources.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
