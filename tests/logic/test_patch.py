"""Reading a `.patch` bundle: zlib-compressed keyed archives (`nodes.plistZ`, `<node>/base.plistZ`)
and the `.cst` strip beside them. The archives here are built the way Logic's own are shaped."""

import plistlib
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

import _paths  # noqa: F401
from _records import rec
from logicxkit.logic.services.mixer.patch import read_patch, unarchive


def archive(top: dict, objects: list) -> bytes:
    """A keyed archive: ``top`` holds plain values or ``uid(n)`` references into ``objects``
    (index 0 is `$null`)."""
    pl = {"$archiver": "WsSplitKeyedArchiver", "$version": 100000, "$objects": ["$null", *objects], "$top": top}
    return zlib.compress(plistlib.dumps(pl, fmt=plistlib.FMT_BINARY))


def uid(n: int) -> dict:
    return {"CF$UID": n}


def cst(label: str) -> bytes:
    """A strip as Logic lays one out: the `OCuA` channel record, a Channel EQ slot, the 14-byte
    `OCuA` terminator."""
    p = bytearray(220)
    p[184:192] = b"GAMETSPP"
    struct.pack_into("<III", p, 172, 24 + 8 * 4, 1, 8)
    struct.pack_into("<I", p, 192, 236)
    return rec(b"OCuA", 0, 0xFFFF, bytes(200)) + rec(b"UCuA", 0, 2, bytes(p)) + rec(b"OCuA", 1, 0xFFFF, bytes(14))


def bundle(root: Path, name: str = "Drums") -> Path:
    patch = root / f"{name}.patch"
    (patch / name).mkdir(parents=True)
    # objects: 1 names array, 2 the name string, 3 NSArray class
    (patch / "nodes.plistZ").write_bytes(archive(
        {"patchesAndSetsExternalNames": uid(1), "VersionPatches": 35014},
        [{"$class": uid(3), "NS.object.0": uid(2)}, name, {"$classname": "NSMutableArray", "$classes": ["NSMutableArray"]}]))
    channel = {"$class": uid(4), "Channel_name": uid(2), "Channel_chaStrName": uid(3), "Channel_channelVolume": 0.7,
               "Channel_pan": 0.0, "Channel_isMuted": False, "Channel_isSolo": False, "Channel_numChannels": 2,
               "Channel_outputIsBus": True, "Channel_outputIndex": 3}
    (patch / name / "base.plistZ").write_bytes(archive(
        {"channels": uid(1), "expanded": False},
        [{"$class": uid(5), "NS.object.0": uid(6)}, "Kick", "001 Kick.cst", {"$classname": "WsConcreteChannel"},
         {"$classname": "NSMutableArray"}, channel]))
    (patch / name / "001 Kick.cst").write_bytes(cst("Kick"))
    return patch


class UnarchiveTest(unittest.TestCase):
    def test_uids_resolve_and_ns_pairs_become_lists(self):
        top = unarchive(archive({"names": uid(1)}, [{"$class": uid(3), "NS.object.0": uid(2)}, "Drums", {"$classname": "NSArray"}]))
        self.assertEqual(top["names"], ["Drums"])


class OldStylePatchTest(unittest.TestCase):
    def test_a_data_plist_patch_reads_its_root_strip(self):
        with tempfile.TemporaryDirectory() as tmp:
            patch = Path(tmp, "Master Echo.patch")
            patch.mkdir()
            (patch / "#Root.cst").write_bytes(cst("Root"))
            (patch / "data.plist").write_bytes(plistlib.dumps({"VersionPatches": 40014, "channels": [
                {"Channel_name": "Master Echo", "Filename": "#Root.cst", "Channel_isMuted": False, "Channel_isSolo": False,
                 "Channel_outputIndex": 0, "Channel_outputIsBus": False}]}))
            p = read_patch(patch)
            (ch,) = p.channels
            self.assertEqual((p.name, ch.name, ch.strip, ch.output, ch.plugins), ("Master Echo", "Master Echo", "#Root.cst", "Output 1", ["Channel EQ"]))


class ReadPatchTest(unittest.TestCase):
    def test_a_patch_names_its_nodes_channels_and_strips(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = read_patch(bundle(Path(tmp)))
            self.assertEqual((p.name, p.nodes), ("Drums", ["Drums"]))
            (ch,) = p.channels
            self.assertEqual((ch.name, ch.strip, ch.volume, ch.width, ch.output), ("Kick", "001 Kick.cst", 0.7, 2, "Bus 4"))
            self.assertEqual(ch.plugins, ["Channel EQ"])


if __name__ == "__main__":
    unittest.main()

