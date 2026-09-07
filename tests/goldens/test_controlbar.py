"""Control bar and display: names to ids, the plist and its archive written together, and the
single-toggle saves (golden `controlbar-saves`, cb-*) as goldens when present.

The real-file part of tests/logic/test_controlbar.py; skips without the owner's files."""

import plistlib
import tempfile
import unittest
from pathlib import Path
import _goldens
import _paths  # noqa: F401
from logicxkit.logic.services.controlbar import (
    LAYOUT_KEY, TRANSPORT_KEY, copy_layout, read_controls, read_layout,
    with_controls,
)

GOLDENS = _goldens.path("controlbar-saves") or _paths.RESOURCES / "missing"
def archived(alt: Path) -> dict:
    """The whole archive dereferenced: every dictionary by its keys."""
    plist = plistlib.loads((alt / "DisplayStateArchive").read_bytes())
    objs = plist["$objects"]
    def deref(v):
        if isinstance(v, plistlib.UID):
            v = objs[v.data]
        if isinstance(v, dict) and "NS.keys" in v:
            return {deref(k): deref(x) for k, x in zip(v["NS.keys"], v["NS.objects"], strict=True)}
        if isinstance(v, dict) and "NS.objects" in v:
            return [deref(x) for x in v["NS.objects"]]
        return v
    return deref(next(iter(plist["$top"].values())))


@unittest.skipUnless((GOLDENS / "cb-01-go-to-beginning-b.logicx").exists(), "single-toggle saves absent")
class GoldenTest(unittest.TestCase):
    """Consecutive saves differ in exactly the control that was toggled."""
    TOGGLES = [("cb-01-go-to-beginning-b", "cb-02-go-to-position", "Go to Position", True),
               ("cb-10-play-from-selection", "cb-11-pause", "Pause", True),
               ("cb-15-sample-rate", "cb-16-varispeed", "Varispeed", True),
               ("cb-19-autopunch", "cb-20-set-punch-by-playhead", "Set Punch In/Out Locator by Playhead", True),
               ("cb-29-library-off", "cb-30-master-volume-off", "Master Volume", False),
               ("cb-30-master-volume-off", "cb-31-output-meter", None, None),
               ("cb-34-solo-off", "cb-35-count-in-off", "Count In", False),
               ("cb-38-positions-off", "cb-39-performance-meter-off", "Performance Meter (CPU/HD)", False)]

    def test_each_save_moves_one_control(self):
        for before, after, name, on in self.TOGGLES:
            with self.subTest(after):
                a = read_controls(next((GOLDENS / f"{before}.logicx").parent.glob(f"{before}.logicx/Alternatives/000")))
                b = read_controls(next((GOLDENS / f"{after}.logicx").glob("Alternatives/000")))
                changed = {k for k in a if a[k] != b[k]}
                if name is None:                                  # box back on + popup to Output Meter
                    self.assertEqual(changed, {"Master Volume", "Output Meter"})
                else:
                    self.assertEqual(changed, {name})
                    self.assertEqual(b[name], on)

    def test_a_real_archive_changes_only_the_written_keys(self):
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp) / "x.logicx"
            shutil.copytree(GOLDENS / "cb-01-go-to-beginning-b.logicx", dst)
            alt = dst / "Alternatives" / "000"
            plist = plistlib.loads((alt / "DisplayStateArchive").read_bytes())
            before = archived(alt)
            copy_layout(GOLDENS / "cb-44-display-time.logicx/Alternatives/000", alt)
            after = archived(alt)
            plist2 = plistlib.loads((alt / "DisplayStateArchive").read_bytes())
            self.assertGreater(len(plist2["$objects"]), len(plist["$objects"]))
            def flatten(o, path=""):
                if isinstance(o, dict):
                    for k, v in o.items():
                        yield from flatten(v, f"{path}/{k}")
                elif isinstance(o, list):
                    for i, v in enumerate(o):
                        yield from flatten(v, f"{path}[{i}]")
                else:
                    yield path, o
            a, b = dict(flatten(before)), dict(flatten(after))
            changed = {k for k in set(a) | set(b) if a.get(k) != b.get(k)}
            self.assertTrue(changed)
            self.assertTrue(all(LAYOUT_KEY in k or TRANSPORT_KEY in k for k in changed), sorted(changed)[:10])
            self.assertEqual(after["screensetDictArray"][0]["layoutDictArray"][0]["docwWindowState"][TRANSPORT_KEY]["DisplayMode"], 1)

    def test_with_controls_reproduces_logics_lists(self):
        for before, after, want in (("cb-10-play-from-selection", "cb-11-pause", {"Pause": True}),
                                    ("cb-15-sample-rate", "cb-16-varispeed", {"Varispeed": True}),
                                    ("cb-30-master-volume-off", "cb-31-output-meter", {"Master Volume": True, "Output Meter": True}),
                                    ("cb-42-tempo-off", "cb-43-master-volume-popup", {"Output Meter": False})):
            with self.subTest(after):
                base = read_layout(GOLDENS / f"{before}.logicx/Alternatives/000")[0]
                logic = read_layout(GOLDENS / f"{after}.logicx/Alternatives/000")[0]
                self.assertEqual(with_controls(base, want), logic)


if __name__ == "__main__":
    unittest.main()
