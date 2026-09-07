"""Retrack — rewrite a project's channel-strip references to their tracking equivalents.

Channels load their chain from a `.cst` reference (proven in Logic: changing only the
reference string changed which strip loaded). The reference is a 64-byte null-padded field
inside a UCuA record at tag+52, immediately followed by a 64-byte category — so repointing
is length-preserving, which is the whole safety argument: no size fields, no offset math.
"""

import struct
import tempfile
import unittest
from pathlib import Path

from logicxkit.logic import cst_references, retrack

FIELD = 64


def ref_record(name: str, category: str) -> bytes:
    """A UCuA record whose payload puts the name at tag+52, then the category."""
    head = bytearray(36)
    head[0:4] = b"UCuA"
    payload = (b"\x00" * 16 + name.encode().ljust(FIELD, b"\x00")
               + category.encode().ljust(FIELD, b"\x00") + b"\x00" * 32)
    struct.pack_into("<I", head, 28, len(payload))
    return bytes(head) + payload


def project(*names: tuple[str, str]) -> bytes:
    body = b"".join(ref_record(n, c) for n, c in names)
    head = bytearray(b"HDR!" + b"\x00" * 20)
    struct.pack_into("<I", head, 0x10, len(body))
    return bytes(head) + body


class ReadReferencesTest(unittest.TestCase):
    def test_finds_name_and_category(self):
        data = project(("Kick In.cst", "Drums"), ("Vox - Lead.cst", "Vocals"))
        self.assertEqual([(r.name, r.category) for r in cst_references(data)],
                         [("Kick In.cst", "Drums"), ("Vox - Lead.cst", "Vocals")])

    def test_ignores_a_cst_string_not_at_the_record_offset(self):
        self.assertEqual(cst_references(b"loose Kick In.cst text"), [])


class RetrackTest(unittest.TestCase):
    MAP = {"Kick In.cst": "Trk - Kick In.cst", "Vox - Lead.cst": "Trk - Vox.cst"}

    def setUp(self):
        self.data = project(("Kick In.cst", "Drums"), ("Vox - Lead.cst", "Vocals"),
                            ("Guitar SLO.cst", "Guitar"))

    def test_length_is_never_changed(self):
        out, _ = retrack(self.data, self.MAP, "Tracking Rec")
        self.assertEqual(len(out), len(self.data), "repointing must be length-preserving")

    def test_repoints_mapped_and_leaves_the_rest(self):
        out, report = retrack(self.data, self.MAP, "Tracking Rec")
        self.assertEqual([(r.name, r.category) for r in cst_references(out)],
                         [("Trk - Kick In.cst", "Tracking Rec"),
                          ("Trk - Vox.cst", "Tracking Rec"),
                          ("Guitar SLO.cst", "Guitar")])
        self.assertEqual(report["repointed"], 2)
        self.assertEqual(report["untouched"], ["Guitar SLO.cst"])

    def test_no_stale_bytes_when_new_name_is_shorter(self):
        data = project(("A Very Long Strip Name Indeed.cst", "Drums"))
        out, _ = retrack(data, {"A Very Long Strip Name Indeed.cst": "Short.cst"}, "Cat")
        self.assertNotIn(b"Indeed", out)

    def test_rejects_a_name_too_long_for_the_field(self):
        with self.assertRaises(ValueError):
            retrack(self.data, {"Kick In.cst": "x" * 61 + ".cst"}, "Cat")

    def test_is_idempotent(self):
        once, _ = retrack(self.data, self.MAP, "Tracking Rec")
        twice, report = retrack(once, self.MAP, "Tracking Rec")
        self.assertEqual(once, twice)
        self.assertEqual(report["repointed"], 0)

    def test_reports_unmapped_names_for_review(self):
        _out, report = retrack(self.data, self.MAP, "Tracking Rec")
        self.assertIn("Guitar SLO.cst", report["untouched"])


class BundleCopyTest(unittest.TestCase):
    """A Logic project is often a FOLDER holding the .logicx plus a sibling `Audio Files`
    directory (the bundle's own Media/ is empty). Copying only the .logicx would strip the
    audio, so the tool copies exactly what it was pointed at."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def _make_project(self, folder: Path, with_audio: bool) -> Path:
        alt = folder / "Song.logicx/Alternatives/000"
        alt.mkdir(parents=True)
        (alt / "ProjectData").write_bytes(project(("Kick In.cst", "Drums")))
        if with_audio:
            (folder / "Audio Files").mkdir()
            (folder / "Audio Files/take.wav").write_bytes(b"RIFF" + b"\x00" * 64)
        return folder / "Song.logicx"

    def test_project_folder_copies_audio_siblings(self):
        from logicxkit.logic import retrack_bundle
        src = self.root / "in/Song"
        src.mkdir(parents=True)
        self._make_project(src, with_audio=True)
        out = self.root / "out"
        r = retrack_bundle(src, out, {"Kick In.cst": "Trk - Kick In.cst"}, "Cat")
        self.assertTrue((out / "Song/Audio Files/take.wav").exists(),
                        "sibling audio must come along or the project loses its takes")
        self.assertEqual(r["repointed"], 1)

    def test_pointing_at_the_logicx_copies_just_it(self):
        from logicxkit.logic import retrack_bundle
        src = self.root / "in2"
        src.mkdir(parents=True)
        proj = self._make_project(src, with_audio=False)
        out = self.root / "out2"
        r = retrack_bundle(proj, out, {"Kick In.cst": "Trk - Kick In.cst"}, "Cat")
        self.assertTrue((out / "Song.logicx/Alternatives/000/ProjectData").exists())
        self.assertEqual(r["repointed"], 1)

    def test_input_is_never_modified(self):
        from logicxkit.logic import retrack_bundle
        src = self.root / "in3"
        src.mkdir(parents=True)
        self._make_project(src, with_audio=True)
        before = (src / "Song.logicx/Alternatives/000/ProjectData").read_bytes()
        retrack_bundle(src, self.root / "out3", {"Kick In.cst": "Trk - Kick In.cst"}, "Cat")
        self.assertEqual((src / "Song.logicx/Alternatives/000/ProjectData").read_bytes(), before)


class PerEntryCategoryTest(unittest.TestCase):
    """Strips live in different folders (Drums / Bass / Vocals / Instrument), and Logic's
    category IS the immediate parent folder — so a single global category cannot be right for
    a mapping whose targets are spread across folders."""

    def test_mapping_entry_may_carry_its_own_category(self):
        data = project(("Kick In.cst", "Drums"), ("Vox - Lead.cst", "Vocals"))
        out, _ = retrack(data, {
            "Kick In.cst": {"name": "Trk - Kick In.cst", "category": "Drums"},
            "Vox - Lead.cst": {"name": "Trk - Vox.cst", "category": "Vocals"},
        }, "FALLBACK")
        self.assertEqual([(r.name, r.category) for r in cst_references(out)],
                         [("Trk - Kick In.cst", "Drums"),
                          ("Trk - Vox.cst", "Vocals")])

    def test_plain_string_entry_still_uses_the_default_category(self):
        data = project(("Kick In.cst", "Drums"),)
        out, _ = retrack(data, {"Kick In.cst": "Trk - Kick In.cst"}, "Tracking Rec")
        self.assertEqual(cst_references(out)[0].category, "Tracking Rec")


class ProjectFolderTest(unittest.TestCase):
    """A bundle given by its own path still brings its `Audio Files` along."""

    def test_the_bundle_path_copies_the_folder_around_it(self):
        import tempfile

        from logicxkit.logic.services.retrack import copy_project
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "in/Song"
            bundle = folder / "Song.logicx"
            (bundle / "Alternatives/000").mkdir(parents=True)
            (bundle / "Alternatives/000/ProjectData").write_bytes(b"x")
            (folder / "Audio Files").mkdir()
            (folder / "Audio Files/take.wav").write_bytes(b"RIFF" + b"\x00" * 64)
            copied = copy_project(bundle, root / "out")
            self.assertEqual(copied["dest"], root / "out/Song/Song.logicx")
            self.assertTrue((root / "out/Song/Audio Files/take.wav").exists())

    def test_a_bundle_without_audio_beside_it_copies_alone(self):
        import tempfile

        from logicxkit.logic.services.retrack import copy_project
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = root / "in/templates/Song.logicx"
            (bundle / "Alternatives/000").mkdir(parents=True)
            (bundle / "Alternatives/000/ProjectData").write_bytes(b"x")
            copied = copy_project(bundle, root / "out")
            self.assertEqual(copied["dest"], root / "out/Song.logicx")


class DestructiveOutputGuardTest(unittest.TestCase):
    """`--out` pointing at (or into) the input's own location must never delete the input.

    `--out in` is one keystroke from the documented `--out out`, so a copy that cleared its
    destination before writing would take the source project and its audio with it.
    """

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.src = self.root / "in/Song"
        (self.src / "Song.logicx/Alternatives/000").mkdir(parents=True)
        (self.src / "Song.logicx/Alternatives/000/ProjectData").write_bytes(
            project(("Kick In.cst", "Drums")))
        (self.src / "Audio Files").mkdir()
        (self.src / "Audio Files/take.wav").write_bytes(b"RIFF" + b"\x00" * 64)

    def _run(self, out):
        from logicxkit.logic import retrack_bundle
        return retrack_bundle(self.src, out, {"Kick In.cst": "Trk - Kick In.cst"}, "Drums")

    def test_out_equal_to_source_parent_is_refused(self):
        with self.assertRaises(ValueError):
            self._run(self.src.parent)
        self.assertTrue((self.src / "Audio Files/take.wav").exists(), "source must survive")

    def test_out_inside_the_source_is_refused(self):
        with self.assertRaises(ValueError):
            self._run(self.src / "nested")
        self.assertTrue((self.src / "Audio Files/take.wav").exists())

    def test_symlinked_out_aliasing_the_source_is_refused(self):
        link = self.root / "link"
        link.symlink_to(self.src.parent)
        with self.assertRaises(ValueError):
            self._run(link)
        self.assertTrue((self.src / "Audio Files/take.wav").exists())

    def test_missing_input_does_not_destroy_a_previous_output(self):
        out = self.root / "out"
        self._run(out)
        stamp = out / "Song/Audio Files/take.wav"
        self.assertTrue(stamp.exists())
        from logicxkit.logic import retrack_bundle
        with self.assertRaises((ValueError, FileNotFoundError)):
            retrack_bundle(self.root / "in/Gone", out, {}, "Drums")
        self.assertTrue(stamp.exists(), "a failed run must not delete the previous output")

    def test_normal_out_still_works(self):
        r = self._run(self.root / "out")
        self.assertEqual(r["repointed"], 1)


class NestedOutputTest(unittest.TestCase):
    """`--out` names the directory the copy goes INTO, not the copy itself.

    Aiming it at a previous output nested the new copy inside the stale one, leaving the stale
    build at the path Logic opens — so a correct rebuild looked like it had done nothing.
    """

    def _project(self, root: Path, name: str) -> Path:
        bundle = root / name / f"{name}.logicx"
        (bundle / "Alternatives/000").mkdir(parents=True)
        (bundle / "Alternatives/000/ProjectData").write_bytes(b"\x00" * 64)
        return root / name

    def test_pointing_out_at_a_previous_copy_is_refused(self):
        from logicxkit.logic import copy_project
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = self._project(root / "in", "Song")
            out = root / "out"
            copy_project(src, out)                       # first build: out/Song
            with self.assertRaises(ValueError) as caught:
                copy_project(src, out / "Song")          # the mistake
            self.assertIn("already a copy", str(caught.exception))

    def test_rebuilding_into_the_same_container_replaces_in_place(self):
        from logicxkit.logic import copy_project
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = self._project(root / "in", "Song")
            out = root / "out"
            first = copy_project(src, out)["dest"]
            second = copy_project(src, out)["dest"]
            self.assertEqual(first, second, "same path, no nesting")
            self.assertEqual(sorted(p.name for p in out.iterdir()), ["Song"])


class RetrackChannelsTest(unittest.TestCase):
    """Per-channel repointing: two channels sharing one name part ways, the folder stays."""

    def _project(self):
        from _records import chan, proj, rec
        def ref(owner, name, cat):
            p = bytearray(192)
            p[16:16 + len(name)] = name.encode()
            p[80:80 + len(cat)] = cat.encode()
            return rec(b"UCuA", owner, 13, bytes(p), 5)
        return proj(chan(4, "Audio 5"), ref(4, "Rack.cst", "Drums"), chan(6, "Audio 7"), ref(6, "Rack.cst", "Drums"),
                    chan(0, "Audio 1"), ref(0, "Kick In.cst", "Drums"))

    def test_each_channel_gets_its_own_name_and_the_folder_stays(self):
        from logicxkit.logic.services.retrack import cst_references, reference_owner, retrack_channels
        data = self._project()
        out, report = retrack_channels(data, {4: "Rack 1.cst", 6: "Rack 3.cst"})
        got = {reference_owner(out, r): (r.name, r.category) for r in cst_references(out)}
        self.assertEqual(got, {4: ("Rack 1.cst", "Drums"), 6: ("Rack 3.cst", "Drums"), 0: ("Kick In.cst", "Drums")})
        self.assertEqual(len(out), len(data))
        self.assertEqual(report["changes"], [(4, "Rack.cst", "Rack 1.cst"), (6, "Rack.cst", "Rack 3.cst")])

    def test_a_folder_can_move_with_the_name(self):
        from logicxkit.logic.services.retrack import cst_references, reference_owner, retrack_channels
        out, _ = retrack_channels(self._project(), {0: {"name": "Kick.cst", "category": "Cat"}})
        got = {reference_owner(out, r): (r.name, r.category) for r in cst_references(out)}
        self.assertEqual(got[0], ("Kick.cst", "Cat"))

    def test_refusals(self):
        from logicxkit.logic.services.retrack import retrack_channels
        with self.assertRaises(ValueError):
            retrack_channels(self._project(), {99: "Rack 1.cst"})
        with self.assertRaises(ValueError):
            retrack_channels(self._project(), {4: "x" * 70 + ".cst"})
