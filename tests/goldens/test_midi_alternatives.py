"""`logic midi` numbers regions from the listed alternative: an edit finds that region again in
every other alternative by track, start and name, and the listing counts what the edits count."""

import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import _goldens
from logicxkit.cli import main
from logicxkit.logic.services.midi.midi import read_midi
from logicxkit.logic.services.midi.midi_write import add_region
from logicxkit.logic.services.project.project import project_metadata
from logicxkit.logicx import project_data

TWO, METER = "midi-two-notes-logic", "meter-song"
BAR = 3840


def run(command: str, *argv) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        rc = main(["logic", command, *map(str, argv)])
    return rc, buf.getvalue()


@_goldens.needs(TWO)
class AlternativesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.project = self.root / "in" / "two.logicx"
        shutil.copytree(_goldens.path(TWO), self.project)
        shutil.copytree(self.project / "Alternatives" / "000", self.project / "Alternatives" / "001")
        (self.region,) = read_midi(project_data(self.project))
        self.pitches = [e.pitch for e in self.region.events]

    def tearDown(self):
        self.tmp.cleanup()

    def _add(self, alternative: str, name: str, start: int) -> None:
        f = self.project / "Alternatives" / alternative / "ProjectData"
        data, _ = add_region(f.read_bytes(), track="Inst 1", start=start, length=BAR, name=name)
        f.write_bytes(data)

    def _written(self) -> dict[str, list]:
        (project,) = (self.root / "out").rglob("*.logicx")
        return {f.parent.name: [(r.name, r.start, [e.pitch for e in r.events]) for r in read_midi(f.read_bytes())]
                for f in sorted(project.glob("Alternatives/*/ProjectData"))}

    def test_region_n_is_the_same_region_in_every_alternative(self):
        early = self.region.start - 2 * BAR
        self._add("001", "Earlier", early)
        rc, text = run("midi", self.project, "--out", self.root / "out", "--transpose", "1=12")
        self.assertEqual(rc, 0, text)
        edited = ("Inst 1", self.region.start, [p + 12 for p in self.pitches])
        self.assertEqual(self._written(), {"000": [edited], "001": [("Earlier", early, []), edited]})

    def test_an_alternative_without_the_region_is_refused_by_name(self):
        self._add("000", "Only here", self.region.start - 2 * BAR)
        rc, text = run("midi", self.project, "--out", self.root / "out", "--transpose", "1=1")
        self.assertEqual(rc, 1, text)
        self.assertIn("--transpose 1: alternative 001 has no region 'Only here' on 'Inst 1' at bar 1", text)
        self.assertEqual(list((self.root / "out").rglob("ProjectData")), [])

    def test_an_alternative_with_two_such_regions_is_refused(self):
        self._add("001", "Inst 1", self.region.start)
        rc, text = run("midi", self.project, "--out", self.root / "out", "--transpose", "1=1")
        self.assertEqual(rc, 1, text)
        self.assertIn("--transpose 1: alternative 001 has 2 regions 'Inst 1' on 'Inst 1' at bar 3", text)
        self.assertEqual(list((self.root / "out").rglob("ProjectData")), [])


@_goldens.needs(METER)
class ListingCountTest(unittest.TestCase):
    def test_the_listing_numbers_the_regions_the_edits_number(self):
        p = _goldens.path(METER)
        data, count = project_data(p), project_metadata(p).get("tracks")
        regions = read_midi(data, count)
        self.assertNotEqual(len(read_midi(data)), len(regions))          # the metadata count picks the list here
        rc, text = run("midi", p, "--json")
        self.assertEqual(rc, 0, text)
        self.assertEqual([(r["number"], r["start"]) for r in json.loads(text)],
                         [(n, r.start) for n, r in enumerate(regions, 1)])
        for command in ("midi", "regions"):
            rc, text = run(command, p)
            self.assertEqual((rc, f": {len(regions)} MIDI region(s)" in text), (0, True), text)


if __name__ == "__main__":
    unittest.main()
