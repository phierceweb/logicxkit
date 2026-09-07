"""Control bar and display: names to ids, the plist and its archive written together, and the
single-toggle saves (golden `controlbar-saves`, cb-*) as goldens when present."""

import plistlib
import tempfile
import unittest
from pathlib import Path
import _paths  # noqa: F401
from logicxkit.logic.services.controlbar import (
    CONTROLS, LAYOUT_KEY, SECTIONS, TRANSPORT_KEY, controls_of, copy_layout, read_layout,
    with_controls, write_controls, write_layout,
)

BASE_LAYOUT = {
    "CLgTransportBtnsViewLeft": [100, 101], "CLgTransportBtnsViewRight": [110],
    "CLgTransportBtnsTransport": [11, 12, 13, 14, 16, 38], "CLgTransportBtnsDisplay": [18, 19],
    "CLgTransportBtnsModus": [30, 42], "CLgTransportDisplayMode": 0,
}


def uid(n):
    return plistlib.UID(n)


def archive_for(layout: dict, transport: dict, more: list[tuple[dict, dict]] = ()) -> bytes:
    """A DisplayStateArchive shaped like Logic's: keyed-archiver objects, arrays as
    ``NS.objects`` of references, one shared object per int, bool or string, one window
    state per ``(layout, transport)`` pair."""
    objs = ["$null"]
    def add(o):
        objs.append(o)
        return uid(len(objs) - 1)
    scalars = {}
    def scalar(v):
        key = (type(v), v)
        if key not in scalars:
            scalars[key] = add(v)
        return scalars[key]
    array_class = add({"$classname": "NSArray", "$classes": ["NSArray", "NSObject"]})
    def window(layout, transport):
        keys, vals = [], []
        for k, v in layout.items():
            keys.append(scalar(k))
            vals.append(add({"$class": array_class, "NS.objects": [scalar(int(i)) for i in v]}) if isinstance(v, list) else scalar(v))
        layout_dict = add({"NS.keys": keys, "NS.objects": vals})
        t_dict = add({"NS.keys": [scalar(k) for k in transport], "NS.objects": [scalar(v) for v in transport.values()]})
        return add({"NS.keys": [scalar(LAYOUT_KEY), scalar(TRANSPORT_KEY)], "NS.objects": [layout_dict, t_dict]})
    windows = [window(layout, transport)] + [window(lo, tr) for lo, tr in more]
    unrelated = add({"NS.keys": [scalar("listsAreVisible"), scalar("flags")], "NS.objects": [scalar(False), scalar(0)]})
    add({"NS.keys": [scalar("windows"), scalar("other")], "NS.objects": [add({"$class": array_class, "NS.objects": windows}), unrelated]})
    return plistlib.dumps({"$version": 100000, "$archiver": "NSKeyedArchiver", "$top": {"root": uid(len(objs) - 1)},
                           "$objects": objs}, fmt=plistlib.FMT_BINARY)


def alternative(root: Path, layout: dict, transport: dict, *, archive: bool = True,
                more: list[tuple[dict, dict]] = ()) -> Path:
    """An alternative with one main window per ``(layout, transport)`` pair, each in its own
    screenset, in both display-state files."""
    alt = root / "Alternatives" / "000"
    alt.mkdir(parents=True)
    def window(lo, tr):
        return {"layoutDictArray": [{"docwWindowState": {
            LAYOUT_KEY: {k: list(v) if isinstance(v, list) else v for k, v in lo.items()},
            TRANSPORT_KEY: dict(tr), "windowFrame": "0 0 1 1"}}]}
    state = {"screensetDictArray": [window(layout, transport)] + [window(lo, tr) for lo, tr in more]}
    (alt / "DisplayState.plist").write_bytes(plistlib.dumps(state, fmt=plistlib.FMT_BINARY))
    if archive:
        (alt / "DisplayStateArchive").write_bytes(archive_for(layout, transport, more))
    return alt


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


def archived_windows(alt: Path) -> list[tuple[dict, dict]]:
    """``(layout, transport)`` per archived window."""
    return [(w[LAYOUT_KEY], w[TRANSPORT_KEY]) for w in archived(alt)["windows"]]


def archived_layout(alt: Path) -> tuple[dict, dict]:
    return archived_windows(alt)[0]


def plist_windows(alt: Path) -> list[tuple[dict, dict]]:
    state = plistlib.loads((alt / "DisplayState.plist").read_bytes())
    return [(w["layoutDictArray"][0]["docwWindowState"][LAYOUT_KEY], w["layoutDictArray"][0]["docwWindowState"][TRANSPORT_KEY])
            for w in state["screensetDictArray"]]


class TableTest(unittest.TestCase):
    def test_every_id_belongs_to_one_named_control_per_section(self):
        seen = {}
        for name, pairs in CONTROLS.items():
            for section, i in pairs:
                self.assertIn(section, SECTIONS)
                self.assertNotIn((section, i), seen, f"{(section, i)} named twice: {seen.get((section, i))}, {name}")
                seen[(section, i)] = name
        self.assertEqual(len(seen), 63)

    def test_controls_of_reads_a_layout(self):
        state = controls_of(BASE_LAYOUT)
        self.assertTrue(state["Library"] and state["Play"] and state["Master Volume"])
        self.assertFalse(state["Pause"] or state["Varispeed"] or state["Output Meter"])

    def test_with_controls_appends_and_removes_every_id(self):
        new = with_controls(BASE_LAYOUT, {"Pause": True, "Varispeed": True, "Set Left/Right Locator by Playhead": True,
                                          "Play": False})
        self.assertEqual(new["CLgTransportBtnsTransport"], [11, 12, 13, 15, 16, 38])
        self.assertEqual(new["CLgTransportBtnsDisplay"], [18, 19, 46])
        self.assertEqual(new["CLgTransportBtnsModus"], [30, 42, 31, 32, 46])
        self.assertEqual(BASE_LAYOUT["CLgTransportBtnsTransport"], [11, 12, 13, 14, 16, 38])   # untouched
        back = with_controls(new, {"Varispeed": False, "Set Left/Right Locator by Playhead": False})
        self.assertEqual((back["CLgTransportBtnsDisplay"], back["CLgTransportBtnsModus"]), ([18, 19], [30, 42]))


class WriteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.alt = alternative(root / "a.logicx", BASE_LAYOUT, {"UseSMPTEViewOffset": False, "DisplayMode": 0})
        self.other = alternative(root / "b.logicx", {**BASE_LAYOUT, "CLgTransportBtnsTransport": [6, 14, 38],
                                                     "CLgTransportBtnsModus": [30, 53, 47]},
                                 {"UseSMPTEViewOffset": False, "DisplayMode": 1})

    def tearDown(self):
        self.tmp.cleanup()

    def test_write_controls_updates_the_plist_and_the_archive_alike(self):
        state = write_controls(self.alt, {"Pause": True, "Library": False})
        self.assertTrue(state["Pause"])
        self.assertFalse(state["Library"])
        layout, _t = read_layout(self.alt)
        self.assertEqual(layout["CLgTransportBtnsTransport"], [11, 12, 13, 14, 15, 16, 38])
        self.assertEqual(layout["CLgTransportBtnsViewLeft"], [101])
        archived, _t = archived_layout(self.alt)
        self.assertEqual(archived, layout)

    def test_copy_layout_carries_lists_verbatim_and_the_lcd_mode(self):
        copied = copy_layout(self.other, self.alt)
        self.assertTrue(copied["Go to Beginning"] and copied["Output Meter"] and copied["Tuner"])
        layout, transport = read_layout(self.alt)
        self.assertEqual(layout["CLgTransportBtnsTransport"], [6, 14, 38])
        self.assertEqual(transport, {"UseSMPTEViewOffset": False, "DisplayMode": 1})
        self.assertEqual(archived_layout(self.alt), (layout, transport))

    def test_a_shared_scalar_is_repointed_not_rewritten(self):
        """The archive keeps one object per value; the LCD mode must not drag ``flags`` and
        ``listsAreVisible`` along with it."""
        before = archived(self.alt)
        write_layout(self.alt, BASE_LAYOUT, {"UseSMPTEViewOffset": True, "DisplayMode": 1})
        after = archived(self.alt)
        self.assertEqual(archived_windows(self.alt)[0][1], {"UseSMPTEViewOffset": True, "DisplayMode": 1})
        self.assertEqual(after["other"], before["other"])
        self.assertEqual(archived_windows(self.alt)[0][0], before["windows"][0][LAYOUT_KEY])

    def test_every_window_is_written_in_both_files_even_without_a_display_mode(self):
        """A mix with four screensets keeps the LCD mode in one window only; the other three
        carry just the SMPTE flag. Every window's layout and LCD state must land in both files."""
        alt = alternative(Path(self.tmp.name) / "d.logicx", BASE_LAYOUT, {"UseSMPTEViewOffset": False, "DisplayMode": 0},
                          more=[(BASE_LAYOUT, {"UseSMPTEViewOffset": False}), (BASE_LAYOUT, {"UseSMPTEViewOffset": False})])
        copy_layout(self.other, alt)
        want_layout, want_transport = read_layout(self.other)
        for lo, tr in plist_windows(alt) + archived_windows(alt):
            self.assertEqual(lo, want_layout)
            self.assertEqual(tr, want_transport)
        write_controls(alt, {"Pause": True})
        for lo, _tr in plist_windows(alt) + archived_windows(alt):
            self.assertIn(15, lo["CLgTransportBtnsTransport"])


if __name__ == "__main__":
    unittest.main()
