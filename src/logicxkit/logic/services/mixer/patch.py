"""A `.patch` bundle — Logic's Library patch: one folder per node, each holding zlib-compressed
keyed archives (`base.plistZ` with the channel's settings, `mappings.plistZ` and `uidata.plistZ`
with the Smart Controls) and the channel's `.cst` strip; `nodes.plistZ` at the top names the
nodes. The older shape is one `data.plist` (a plain plist with the same `Channel_*` keys) beside a
`#Root.cst` — the shape Logic 12.3.1 writes from the Library's Save (2026-09-13), and the one
`build_patch` makes. Read from Logic's own default patches; the archives are `NSKeyedArchiver`
shaped, `$top` keys pointing into `$objects` by `CF$UID`.
"""

from __future__ import annotations

import plistlib
import shutil
import uuid as _uuid
import zlib
from dataclasses import dataclass
from pathlib import Path

from .mixer import CHANNEL_TAG
from ..stream.stream import HEADER, NO_KEY, project_records
from .library import require_plain_names
from .plugins import _ref
from .stripsave import _STUB

NODES = "nodes.plistZ"
BASE = "base.plistZ"
DATA = "data.plist"
_DEPTH = 24


def _key(k):
    """A dict key from a resolved value: an object (a UUID holder) keys by its repr."""
    return k if isinstance(k, (str, int, float, bytes, bool, type(None))) else repr(k)


def unarchive(blob: bytes) -> dict:
    """The archive's `$top`, every `CF$UID` resolved, `NS.object.N`/`NS.key.N` pairs turned into
    lists and dicts, class markers dropped."""
    pl = plistlib.loads(zlib.decompress(blob))
    objects = pl["$objects"]

    def resolve(v, depth=0):
        if depth > _DEPTH:
            return None
        if isinstance(v, dict) and "CF$UID" in v:
            return resolve(objects[v["CF$UID"]], depth + 1)
        if isinstance(v, dict):
            if "$classname" in v:
                return v["$classname"]
            if any(k.startswith("NS.key.") for k in v):
                keys = {int(k[7:]): resolve(x, depth + 1) for k, x in v.items() if k.startswith("NS.key.")}
                vals = {int(k[10:]): resolve(x, depth + 1) for k, x in v.items() if k.startswith("NS.object.")}
                return {_key(keys[i]): vals.get(i) for i in sorted(keys)}
            if any(k.startswith("NS.object.") for k in v):
                vals = {int(k[10:]): resolve(x, depth + 1) for k, x in v.items() if k.startswith("NS.object.")}
                return [vals[i] for i in sorted(vals)]
            return {k: resolve(x, depth + 1) for k, x in v.items() if k != "$class"}
        if isinstance(v, list):
            return [resolve(x, depth + 1) for x in v]
        return None if v == "$null" else v

    return {k: resolve(v) for k, v in pl["$top"].items()}


@dataclass(frozen=True)
class PatchChannel:
    name: str
    strip: str | None           # the .cst file name beside base.plistZ
    volume: float | None        # Logic's 0-1 fader value, when the plist carries one
    pan: float | None
    muted: bool
    solo: bool
    width: int | None           # 1 mono, 2 stereo
    output: str | None          # "Bus N" or "Output N"
    plugins: list[str]
    fader: int | None = None    # the .cst channel record's fader byte (unity 90) and pan byte (centre 64)
    pan_byte: int | None = None


@dataclass(frozen=True)
class Patch:
    path: Path
    name: str
    nodes: list[str]
    channels: list[PatchChannel]


def _io(index, is_bus) -> str | None:
    if index is None:
        return None
    return f"{'Bus' if is_bus else 'Output'} {int(index) + 1}"


def _plugins(cst: Path | None) -> list[str]:
    if cst is None or not cst.is_file():
        return []
    out = []
    for r in project_records(cst.read_bytes(), start=0):
        if r.tag == b"UCuA":
            ref = _ref("", r.key, r.raw[HEADER:])
            if ref is not None:
                out.append(ref.name)
    return out


def _levels(cst: Path | None) -> tuple[int | None, int | None]:
    """The fader and pan bytes of the strip's channel record, at a project channel's offsets (`levels.py`)."""
    from .levels import FADER_AT, PAN_AT, _is_mixer_channel
    if cst is None or not cst.is_file():
        return None, None
    for r in project_records(cst.read_bytes(), start=0):
        if _is_mixer_channel(r):
            payload = r.raw[HEADER:]
            return payload[FADER_AT[1]], payload[PAN_AT]
    return None, None


def _channel(node: Path, ch: dict) -> PatchChannel:
    strip = ch.get("Channel_chaStrName") or ch.get("Filename")
    cst = next((p for p in node.glob("*.cst") if p.name.endswith(strip)), None) if strip else next(node.glob("*.cst"), None)
    fader, pan_byte = _levels(cst)
    return PatchChannel(ch.get("Channel_name") or node.name, cst.name if cst else strip, ch.get("Channel_channelVolume"),
                        ch.get("Channel_pan"), bool(ch.get("Channel_isMuted")), bool(ch.get("Channel_isSolo")),
                        ch.get("Channel_numChannels"), _io(ch.get("Channel_outputIndex"), ch.get("Channel_outputIsBus")),
                        _plugins(cst), fader, pan_byte)


def read_patch(path: str | Path) -> Patch:
    path = Path(path)
    if (path / DATA).is_file() and not (path / NODES).is_file():
        pl = plistlib.loads((path / DATA).read_bytes())
        chans = [_channel(path, ch) for ch in pl.get("channels", []) if isinstance(ch, dict)]
        return Patch(path, path.stem, [path.stem], chans)
    if not (path / NODES).is_file():
        raise ValueError(f"{path} has neither {NODES} nor {DATA}: not a Logic patch bundle")
    top = unarchive((path / NODES).read_bytes())
    names = top.get("patchesAndSetsExternalNames") or []
    if isinstance(names, dict):
        names = list(names.values())
    channels = []
    for node in sorted(p for p in path.iterdir() if p.is_dir()):
        if not (node / BASE).is_file():
            continue
        base = unarchive((node / BASE).read_bytes())
        chans = base.get("channels") or []
        if isinstance(chans, dict):
            chans = list(chans.values())
        channels += [_channel(node, ch) for ch in chans if isinstance(ch, dict)]
    return Patch(path, path.stem, [str(n) for n in names], channels)


VERSION_PATCHES = 40014
ROOT_STRIP = "#Root.cst"
DEFAULT_ICON, DEFAULT_COLOUR, DEFAULT_INST_ID = 4643, 16, 88


def strip_bytes(strip: Path) -> bytes:
    """``strip``'s bytes, refused unless they are a channel strip's record stream: the `OCuA`
    channel record, `UCuA` records, the `OCuA` terminator, nothing after it but zero padding."""
    if not strip.is_file():
        raise ValueError(f"{strip} is not a file")
    data = strip.read_bytes()
    records = project_records(data, start=0)
    end = sum(len(r.raw) for r in records)
    if (len(records) < 2 or (records[0].tag, records[0].key) != (CHANNEL_TAG, NO_KEY) or len(records[0].raw) <= len(_STUB)
            or records[-1].tag != CHANNEL_TAG or len(records[-1].raw) != len(_STUB)
            or any(r.tag != b"UCuA" for r in records[1:-1]) or data[end:].strip(b"\0")):
        raise ValueError(f"{strip} is not a Logic channel strip: expected an OCuA channel record, "
                         "UCuA records and the OCuA terminator, and nothing after them")
    return data


class ReplacedBundleLeft(OSError):
    """The new bundle is in place, but the one it replaced could not be removed."""

    def __init__(self, dest: Path, leftover: Path, cause: OSError):
        super().__init__(f"{dest} is built, but the bundle it replaced is still at {leftover} ({cause}); remove it by hand")
        self.dest, self.leftover = dest, leftover


def _occupied(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _move_in(new: Path, dest: Path, overwrite: bool) -> None:
    """``new`` renamed to ``dest``; an existing ``dest`` is set aside first and put back if the
    rename fails."""
    if not _occupied(dest):
        new.rename(dest)
        return
    if not overwrite:
        raise FileExistsError(f"{dest} exists; pass overwrite to replace it")
    old = dest.with_name(f".{_uuid.uuid4().hex}.patch-old")
    dest.rename(old)
    try:
        new.rename(dest)
    except BaseException:
        old.rename(dest)
        raise
    try:
        if old.is_dir() and not old.is_symlink():
            shutil.rmtree(old)
        else:
            old.unlink()
    except OSError as e:
        raise ReplacedBundleLeft(dest, old, e) from e


def build_patch(strip: str | Path, *, name: str, out_dir: str | Path, overwrite: bool = False,
                icon: int = DEFAULT_ICON, colour: int = DEFAULT_COLOUR) -> Path:
    """``<out_dir>/<name>.patch`` holding ``strip`` as `#Root.cst` and the `data.plist` Logic's
    own Library save writes for one audio channel (2026-09-13); the volume and pan stay the
    strip's. Nothing is written unless ``strip`` reads as a channel strip. The bundle is built in
    a hidden sibling and moved into place, so a failure leaves ``out_dir`` as it was; an existing
    bundle is kept unless ``overwrite``, and replaced only once the new one is complete."""
    strip, out_dir = Path(strip), Path(out_dir)
    try:
        require_plain_names([name])
    except ValueError:
        raise ValueError(f"a patch name must be a plain file name: {name!r}") from None
    raw = strip_bytes(strip)
    dest = out_dir / f"{name}.patch"
    if _occupied(dest) and not overwrite:
        raise FileExistsError(f"{dest} exists; pass overwrite to replace it")
    channel = {"Channel_chaStrCategory": "", "Channel_inputIndex_1": 0, "Channel_inputIsBus": False,
               "Channel_inputIsStereo": False, "Channel_instID": DEFAULT_INST_ID, "Channel_isMuted": False,
               "Channel_isSolo": False, "Channel_name": name, "Channel_outputIndex": 0, "Channel_outputIsBus": False,
               "Channel_outputIsStereo": True, "Channel_receiveChannel": 0, "Channel_sends": [{}, {}],
               "Channel_seqColorIndex": colour, "Channel_userDidModifySmartControls": False, "Filename": ROOT_STRIP,
               "Root": True, "Track_icon": icon, "UUID": str(_uuid.uuid4()).upper()}
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out_dir / f".{_uuid.uuid4().hex}.patch-build"
    tmp.mkdir()
    try:
        (tmp / ROOT_STRIP).write_bytes(raw)
        (tmp / DATA).write_bytes(plistlib.dumps({"channels": [channel], "VersionPatches": VERSION_PATCHES}, fmt=plistlib.FMT_BINARY))
        _move_in(tmp, dest, overwrite)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return dest
