"""Control bar and display: names to ids, the plist and its archive written together, and the
single-toggle saves by manifest key when present.

The real-file part of tests/logic/test_controlbar.py; skips without the owner's files."""

import plistlib
import tempfile
import unittest
from pathlib import Path
import _goldens
from logicxkit.logic.services.controlbar import (
    LAYOUT_KEY, TRANSPORT_KEY, copy_layout, read_controls, read_layout,
    with_controls,
)

PAIRS = [("controlbar-base", "controlbar-go-to-position-on"),
         ("controlbar-play-from-selection-on", "controlbar-pause-on"),
         ("controlbar-sample-rate-on", "controlbar-varispeed-on"),
         ("controlbar-autopunch-on", "controlbar-set-punch-by-playhead-on"),
         ("controlbar-library-off", "controlbar-master-volume-off"),
         ("controlbar-master-volume-off", "controlbar-output-meter-on"),
         ("controlbar-solo-off", "controlbar-count-in-off"),
         ("controlbar-positions-off", "controlbar-performance-meter-off"),
         ("controlbar-tempo-off", "controlbar-master-volume-popup")]
KEYS = sorted({k for pair in PAIRS for k in pair} | {"controlbar-display-time"})
PATHS = {k: _goldens.path(k) for k in KEYS}


def alt(key: str) -> Path:
    return next(PATHS[key].glob("Alternatives/000"))


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


@unittest.skipUnless(all(PATHS.values()), "single-toggle saves absent")
class GoldenTest(unittest.TestCase):
    """Consecutive saves differ in exactly the control the manifest says was toggled."""

    def test_each_save_moves_one_control(self):
        for before, after in PAIRS:
            with self.subTest(after):
                a, b = read_controls(alt(before)), read_controls(alt(after))
                changed = {k for k in a if a[k] != b[k]}
                facts = _goldens.entry(after)["facts"]
                if "toggle" in facts:
                    name, on = facts["toggle"]
                    self.assertEqual(changed, {name})
                    self.assertEqual(b[name], on)
                else:
                    self.assertEqual(changed, set(facts.get("changed", facts["set"])))

    def test_a_real_archive_changes_only_the_written_keys(self):
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp) / "x.logicx"
            shutil.copytree(PATHS["controlbar-base"], dst)
            alt_dir = dst / "Alternatives" / "000"
            plist = plistlib.loads((alt_dir / "DisplayStateArchive").read_bytes())
            before = archived(alt_dir)
            copy_layout(alt("controlbar-display-time"), alt_dir)
            after = archived(alt_dir)
            plist2 = plistlib.loads((alt_dir / "DisplayStateArchive").read_bytes())
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
            self.assertEqual(after["screensetDictArray"][0]["layoutDictArray"][0]["docwWindowState"][TRANSPORT_KEY]["DisplayMode"],
                             _goldens.fact("controlbar-display-time", "display_mode"))

    def test_with_controls_reproduces_logics_lists(self):
        for before, after in PAIRS[1:3] + PAIRS[5:6] + PAIRS[8:9]:
            facts = _goldens.entry(after)["facts"]
            want = facts.get("set") or dict([facts["toggle"]])
            with self.subTest(after):
                self.assertEqual(with_controls(read_layout(alt(before))[0], want), read_layout(alt(after))[0])


if __name__ == "__main__":
    unittest.main()
