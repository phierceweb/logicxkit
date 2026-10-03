"""The plug-in library `add-plugin` draws on: every `donors/` directory's slot records, Logic's
own plug-ins as `donors.harvest_donors` files them (`<type>-v<ver>.slot`, any width — the
writer re-stamps them) and third-party ones as `harvest_au` files them, one per component,
width and class version (`au-<manufacturer>-<subtype>-<mono|stereo>-v<ver>.slot`), since a
third-party slot keeps the width it was saved at. An AU entry carries the instance-id offsets
measured from another instance of the plug-in in the project it came from.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from pathlib import Path

from pf_core.utils.io import atomic_write_bytes, atomic_write_json

from ..._binary import find_blocks
from .plugin_names import native_name
from .donors import MANIFEST, SUFFIX, WIDTH_NAMES, retarget_version
from .slot_width import plugin_variant, slot_format
from .slots import slot_index_base
from ..stream.stream import HEADER, VER_OFF, project_records
from .plugins import plugin_identity
from .plugin_names import plugin_name
from .slots import is_plugin_slot, property_key_base
from .transplant import id_offsets, window_offsets


@dataclass(frozen=True)
class Donor:
    key: str
    raw: bytes
    kind: str                                   # "native" | "au"
    version: int
    name: str | None = None
    type_id: int | None = None
    component: tuple[str, str, str] | None = None
    width: int | None = None                    # None: any, re-stamped on the way in
    id_offsets: tuple[int, ...] = ()

    @property
    def label(self) -> str:
        if self.name:
            return self.name
        if self.component:
            return f"{self.component[2]}/{self.component[1]}"
        return f"type {self.type_id}"

    def matches(self, name: str) -> bool:
        wanted = name.strip().lower()
        codes = {self.label.lower(), str(self.type_id)}
        if self.component:
            codes.add(f"{self.component[2]}/{self.component[1]}".lower())
        return wanted in codes


def load_library(libraries: list[Path]) -> list[Donor]:
    """Every donor in ``libraries``; with several directories the first holding a key wins."""
    out: dict[str, Donor] = {}
    for library in libraries:
        library = Path(library)
        if not library.is_dir():
            continue
        manifest = _read_manifest(library)
        for path in sorted(library.glob(f"*{SUFFIX}")):
            if path.stem in out:
                continue
            donor = _donor(path.stem, path.read_bytes(), manifest.get(path.stem, {}))
            if donor is not None:
                out[path.stem] = donor
    return list(out.values())


def find_donor(donors: list[Donor], name: str, *, width: int | None, version: int | None) -> Donor:
    """The donor named ``name`` (its name, `Manufacturer/Subtype` code or type id) at
    ``version``, of ``width`` when it is third-party; a v5 native donor is retargeted to a v3
    project. Raises LookupError naming what the library has."""
    named = [d for d in donors if d.matches(name)]
    if not named:
        have = ", ".join(sorted({d.label for d in donors})) or "nothing"
        raise LookupError(f"no plug-in named {name!r} in the library; it has: {have}")
    if version is not None:
        exact = [d for d in named if d.version == version]
        if not exact and version == 3:
            exact = [_retargeted(d) for d in named if d.kind == "native" and d.version == 5]
        if not exact:
            have = ", ".join(sorted({f"v{d.version}" for d in named}))
            raise LookupError(f"{name} is in the library at {have}; this project writes v{version}")
        named = exact
    if width is not None:
        fitting = [d for d in named if d.width in (None, width)]
        if not fitting:
            have = ", ".join(sorted({WIDTH_NAMES.get(d.width, str(d.width)) for d in named}))
            want = WIDTH_NAMES.get(width, str(width))
            raise LookupError(f"{name} is in the library only {have}; this channel is {want}. "
                              f"Harvest it from a {want} track.")
        named = fitting
    # a real instance of the channel's width first, then the mono one (re-stamped as needed)
    return sorted(named, key=lambda d: (d.width != width, d.width or 0, d.key))[0]


def library_offsets(donor: Donor, libraries: list[Path]) -> tuple[int, ...]:
    """``donor``'s instance-id bytes, measured against every other record of its plug-in and
    length in ``libraries`` — the package's donor shadows a data root's of one name, yet the two
    are two real instances to measure between."""
    payload = donor.raw[HEADER:]
    identity = plugin_identity(payload)
    others = []
    for library in libraries:
        for path in sorted(Path(library).glob(f"*{SUFFIX}")) if Path(library).is_dir() else ():
            p = path.read_bytes()[HEADER:]
            if p != payload and len(p) == len(payload) and plugin_identity(p) == identity:
                others.append(p)
    return window_offsets(payload, others) if others else ()


def harvest_au(data: bytes, library: Path, *, names: dict[tuple[str, str, str], str] | None = None,
               name: str | None = None, refresh: bool = False) -> list[str]:
    """File one slot per third-party (component, width, version) in ``data``; existing donors
    are kept, or replaced with ``refresh`` (after the plug-in was updated). ``name`` names the
    plug-in harvested — a bare name when the project holds one third-party plug-in, else
    ``SUBTYPE=NAME`` (``FPMb=Pro-MB``); ``names`` maps a component to its name. Returns the keys
    written."""
    library = Path(library)
    library.mkdir(parents=True, exist_ok=True)
    manifest = _read_manifest(library)
    base, first = property_key_base(data), slot_index_base(data)
    slots = []
    for record in project_records(data):
        if is_plugin_slot(record, base, first):
            identity = plugin_identity(record.raw[HEADER:])
            if identity is not None and identity[0] == "au":
                slots.append((record, identity[1:]))
    named = dict(names or {})
    if name and "=" in name:
        sub, _, label = name.partition("=")
        named.update({c: label.strip() for _r, c in slots if c[1] == sub.strip()})
    elif name:
        found = sorted({c for _r, c in slots})
        if len(found) > 1:
            raise ValueError(f"--as {name!r} would name {len(found)} plug-ins; say which: "
                             + ", ".join(f"--as {c[1]}={name}" for c in found))
        named.update({c: name for c in found})
    written = []
    for record, component in slots:
        width = slot_format(record.raw)
        key = f"au-{component[2]}-{component[1]}-{WIDTH_NAMES.get(width, width)}-v{record.ver}"
        path = library / f"{key}{SUFFIX}"
        if key in written or (path.exists() and not refresh):
            continue
        atomic_write_bytes(path, record.raw)
        manifest[key] = {"kind": "au", "component": list(component), "width": width,
                         "version": record.ver, "bytes": len(record.raw) - HEADER,
                         "id_offsets": list(id_offsets(data, record.raw) or ()),
                         "plugin": named.get(component) or f"{component[2]}/{component[1]}"}
        written.append(key)
    if written:
        atomic_write_json(library / MANIFEST, manifest, sort_keys=True, ensure_ascii=True)
    return sorted(written)


def _donor(key: str, raw: bytes, entry: dict) -> Donor | None:
    version = struct.unpack_from("<H", raw, VER_OFF)[0]
    if entry.get("kind") == "au":
        return Donor(key, raw, "au", version, entry.get("plugin"), None, tuple(entry["component"]),
                     entry.get("width"), tuple(entry.get("id_offsets", ())))
    blocks = find_blocks(raw[HEADER:])
    if not blocks:
        return None
    type_id = blocks[0][1]
    name = entry.get("plugin") or plugin_name(raw[HEADER:]) or native_name(type_id, plugin_variant(raw[HEADER:]))
    # a native donor is re-stamped to any width unless its record differs in length by width
    width = entry.get("width") if entry.get("fixed_width") else None
    return Donor(key, raw, "native", version, name, type_id, width=width, id_offsets=tuple(entry.get("id_offsets", ())))


def _retargeted(donor: Donor) -> Donor:
    return Donor(f"{donor.key}->v3", retarget_version(donor.raw, 3), donor.kind, 3, donor.name,
                 donor.type_id, donor.component, donor.width, donor.id_offsets)


def _read_manifest(library: Path) -> dict:
    path = library / MANIFEST
    return json.loads(path.read_text()) if path.exists() else {}
