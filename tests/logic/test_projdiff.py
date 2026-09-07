"""logic diff — project↔project chain/metadata diff and project↔strip-library drift.

Pure functions tested on synthetic reports; CLI tested on synthetic .logicx bundles;
goldens (skip-if-missing) pin the known Recording-vs-Mix delta (the mix-only Stealth
limiter) on the real templates."""

import plistlib
import tempfile
import unittest
from pathlib import Path
from logicxkit.cli import main
from logicxkit.logic.services.projdiff import diff_against_library, diff_projects


def report(channels, bpm=215):
    return {"name": "synthetic", "metadata": {"tracks": 55, "bpm": bpm, "key": "C"},
            "channels": channels, "track_names": []}


def chan(label, chain, cst=None):
    c = {"label": label, "chain": chain}
    if cst:
        c["cst"] = cst
    return c

KICK = chan("Audio 1", [("Channel EQ", None), ("Compressor", None)], cst=["Kick In.cst"])

SNARE = chan("Audio 4", [("Neutron 5", None), ("Pro-Q 4", "Snare - TOP 02")])


class DiffProjectsTest(unittest.TestCase):
    def test_identical_reports_diff_empty(self):
        d = diff_projects(report([KICK, SNARE]), report([KICK, SNARE]))
        self.assertEqual(d["metadata"], {})
        self.assertEqual(d["channels"], [])

    def test_changed_chain_reported_with_both_sides(self):
        snare_b = chan("Audio 4", [("InPhase", None), ("Pro-Q 4", "Snare - TOP 02")])
        d = diff_projects(report([KICK, SNARE]), report([KICK, snare_b]))
        self.assertEqual(len(d["channels"]), 1)
        e = d["channels"][0]
        self.assertEqual((e["label"], e["status"]), ("Audio 4", "changed"))
        self.assertEqual(e["a"][0][0], "Neutron 5")
        self.assertEqual(e["b"][0][0], "InPhase")

    def test_added_and_removed_channels(self):
        d = diff_projects(report([KICK]), report([SNARE]))
        statuses = {e["label"]: e["status"] for e in d["channels"]}
        self.assertEqual(statuses, {"Audio 1": "removed", "Audio 4": "added"})

    def test_metadata_changes(self):
        d = diff_projects(report([KICK], bpm=215), report([KICK], bpm=176))
        self.assertEqual(d["metadata"], {"bpm": (215, 176)})


def _strip_bytes(plugins) -> bytes:
    hdr = b"OCuA\x06\x00\x0e\x00" + b"\x00" * 24 + b" Audio 1\x00" + b"\x00" * 240
    body = b""
    for p in plugins:
        body += b"UCuA\x00\x00" + p.encode() + b"\x00\x00"
    return hdr + body


class DiffAgainstLibraryTest(unittest.TestCase):
    def _lib(self, d, name, plugins):
        p = Path(d, "Track", "X")
        p.mkdir(parents=True, exist_ok=True)
        (p / name).write_bytes(_strip_bytes(plugins))

    def test_match_drift_and_missing(self):
        with tempfile.TemporaryDirectory() as d:
            self._lib(d, "Kick In.cst", ["Channel EQ", "Compressor"])
            self._lib(d, "Snare Down.cst", ["Gain", "Channel EQ"])
            chans = [
                KICK,  # same plugin sequence as saved strip (presets ignored) -> match
                chan("Audio 4", [("InPhase", None), ("Pro-Q 4", None)],
                     cst=["Snare Down.cst"]),  # printed chain != saved strip -> drift
                chan("Audio 9", [("Pro-C 2", None)], cst=["Ghost.cst"]),  # -> missing
            ]
            rows = diff_against_library(report(chans), d)
        by = {(r["label"], r["cst"]): r for r in rows}
        self.assertEqual(by[("Audio 1", "Kick In.cst")]["status"], "match")
        drift = by[("Audio 4", "Snare Down.cst")]
        self.assertEqual(drift["status"], "drift")
        self.assertEqual(drift["strip"], ["Gain", "Channel EQ"])
        self.assertEqual(drift["project"], ["InPhase", "Pro-Q 4"])
        self.assertEqual(by[("Audio 9", "Ghost.cst")]["status"], "missing")

    def test_channels_without_refs_are_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            rows = diff_against_library(report([SNARE]), d)
        self.assertEqual(rows, [])

    def test_refs_with_no_embedded_chain_are_skipped(self):
        # clean-save template channels reference a strip but embed nothing — there is
        # no printed chain to drift, so they must not be reported as drift
        with tempfile.TemporaryDirectory() as d:
            self._lib(d, "Kick In.cst", ["Channel EQ"])
            rows = diff_against_library(
                report([chan("Audio 1", [], cst=["Kick In.cst"])]), d)
        self.assertEqual(rows, [])


def _bundle(d: str, name: str, project_data: bytes, bpm: int = 215) -> str:
    alt = Path(d, name, "Alternatives", "000")
    alt.mkdir(parents=True)
    (alt / "ProjectData").write_bytes(project_data)
    (alt / "MetaData.plist").write_bytes(plistlib.dumps(
        {"NumberOfTracks": 2, "BeatsPerMinute": bpm, "SongKey": "C",
         "SongSignatureNumerator": 4, "SongSignatureDenominator": 4,
         "SampleRate": 44100}))
    return str(Path(d, name))


class CliDiffTest(unittest.TestCase):
    def test_identical_bundles_exit_0_different_exit_1(self):
        pd_a = _strip_bytes(["Channel EQ", "Compressor"])
        pd_b = _strip_bytes(["InPhase", "Compressor"])
        with tempfile.TemporaryDirectory() as d:
            a = _bundle(d, "A.logicx", pd_a)
            a2 = _bundle(d, "A2.logicx", pd_a)
            b = _bundle(d, "B.logicx", pd_b)
            self.assertEqual(main(["logic", "diff", a, a2]), 0)
            self.assertEqual(main(["logic", "diff", a, b]), 1)
            self.assertEqual(main(["logic", "diff", a, b, "--json"]), 1)

    def test_library_mode_exit_codes(self):
        pd = _strip_bytes(["Channel EQ", "Compressor"]) + b"\x00Kick In.cst\x00"
        with tempfile.TemporaryDirectory() as d:
            bundle = _bundle(d, "A.logicx", pd)
            lib = Path(d, "lib")
            lib.mkdir()
            (lib / "Kick In.cst").write_bytes(_strip_bytes(["Channel EQ", "Compressor"]))
            self.assertEqual(main(["logic", "diff", bundle, "--library", str(lib)]), 0)
            (lib / "Kick In.cst").write_bytes(_strip_bytes(["Gain"]))
            self.assertEqual(main(["logic", "diff", bundle, "--library", str(lib)]), 1)


class CliImageTest(unittest.TestCase):
    def test_extracts_window_image(self):
        with tempfile.TemporaryDirectory() as d:
            bundle = _bundle(d, "A.logicx", b"OCuA\x06\x00\x0e\x00")
            img = Path(bundle, "Alternatives", "000", "WindowImage.jpg")
            img.write_bytes(b"\xff\xd8fake-jpeg")
            out = Path(d, "out.jpg")
            self.assertEqual(main(["logic", "image", bundle, "-o", str(out)]), 0)
            self.assertEqual(out.read_bytes(), b"\xff\xd8fake-jpeg")

    def test_missing_image_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as d:
            bundle = _bundle(d, "A.logicx", b"OCuA\x06\x00\x0e\x00")
            self.assertEqual(
                main(["logic", "image", bundle, "-o", str(Path(d, "x.jpg"))]), 1)


if __name__ == "__main__":
    unittest.main()
