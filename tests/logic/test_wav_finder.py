"""Where a region's WAV is read from: `--audio` first, then the project's own Media and the
`Audio Files` beside it, then the file record's folder unless another project owns it."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import _paths  # noqa: F401

from logicxkit.logic._quantize_cmd import _owner, _wav_finder


def wav(folder: Path, name: str = "take.wav") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(b"RIFF")
    return folder / name


def region(folder: Path, name: str = "take") -> SimpleNamespace:
    return SimpleNamespace(name=name, file=SimpleNamespace(name=f"{name}.wav", folder=str(folder)))


class WavFinderTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.bundle = self.root / "proj" / "Song.logicx"
        data = self.bundle / "Alternatives" / "000" / "ProjectData"
        data.parent.mkdir(parents=True)
        data.write_bytes(b"")
        self.data = data
        self.media = self.bundle / "Media" / "Audio Files"
        self.other = self.root / "other" / "Other.logicx" / "Media" / "Audio Files"
        (self.root / "other" / "Other.logicx" / "Alternatives").mkdir(parents=True)

    def find(self, r, audio: Path | None = None):
        return _wav_finder(self.data, str(audio) if audio else None)(r)

    def test_the_projects_own_media_wins_over_the_bundle_its_records_name(self):
        own, _theirs = wav(self.media), wav(self.other)
        self.assertEqual(self.find(region(self.other)), own)

    def test_another_projects_audio_is_never_read(self):
        wav(self.other)
        self.assertIsNone(self.find(region(self.other)))

    def test_audio_outside_any_project_is_read_where_the_record_says(self):
        outside = wav(self.root / "recordings")
        self.assertEqual(self.find(region(self.root / "recordings")), outside)

    def test_audio_dir_is_read_first(self):
        wav(self.media)
        given = wav(self.root / "given")
        self.assertEqual(self.find(region(self.media), self.root / "given"), given)

    def test_the_audio_files_beside_the_bundle_are_the_projects_own(self):
        beside = wav(self.root / "proj" / "Audio Files")
        self.assertEqual(_owner(self.root / "proj" / "Audio Files"), (self.root / "proj").resolve())
        self.assertEqual(self.find(region(self.root / "nowhere")), beside)          # found by the folder, not the record

    def test_a_take_is_the_records_own_when_its_name_agrees_else_the_latest_by_number(self):
        for n in (2, 4, 9, 10):
            wav(self.media, f"Kick In#{n:02d}.wav" if n < 10 else f"Kick In#{n}.wav")
        r = SimpleNamespace(name="Kick In#04", file=SimpleNamespace(name="Kick In#02.wav", folder=str(self.media)))
        self.assertEqual(self.find(r).name, "Kick In#02.wav")                      # the record's own when its name agrees
        other = SimpleNamespace(name="Snare", file=SimpleNamespace(name="Kick In#02.wav", folder=str(self.media)))
        wav(self.media, "Snare#9.wav"), wav(self.media, "Snare#10.wav")
        self.assertEqual(self.find(other).name, "Snare#10.wav")                    # else the latest take, by number

    def test_a_region_with_no_file_of_its_name_falls_back_to_its_record(self):
        own = wav(self.media, "take.wav")
        r = SimpleNamespace(name="renamed", file=SimpleNamespace(name="take.wav", folder=str(self.media)))
        self.assertEqual(self.find(r), own)

    def test_the_owner_of_a_folder(self):
        self.assertEqual(_owner(self.media), self.bundle.resolve())
        self.assertEqual(_owner(self.other), (self.root / "other" / "Other.logicx").resolve())
        self.assertIsNone(_owner(self.root / "recordings"))


if __name__ == "__main__":
    unittest.main()
