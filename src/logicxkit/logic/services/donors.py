"""A persistent library of plugin-slot donor records.

Inserting a plugin requires a real Logic-written slot record of that plugin at the target
project's class version — the format is not synthesisable. Sourcing donors from whichever
project happens to be open is fragile: the Enveloper exists in no session at all, and no native
reverb existed anywhere until one was saved deliberately.

This keeps harvested records in the repo, keyed by ``<type id>-v<class version>``, so any
project can be given any plugin the library has seen. Donors are only interchangeable within a
class version, so the key carries it and the caller checks.

A v5 record can be **retargeted down to v3** when the library has no v3 donor — see
``retarget_version``. The reverse is not derivable and is refused.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

from pf_core.utils.io import atomic_write_bytes, atomic_write_json

from .._binary import find_blocks
from .insert import HEADER, VER_OFF, project_records

SUFFIX = ".slot"
MANIFEST = "manifest.json"


# The v3 <-> v5 record schema differs in exactly three places, measured by diffing the library's
# own v3/v5 pairs for Channel EQ, Compressor, Echo and Klopfgeist — four plugins of very
# different sizes, all showing the same delta and nothing else:
#
#   payload +0     u32 schema constant   464 at v3, 424 at v5
#   payload +116   u16 plugin-variant id  absent (0) at v3
#   end            4 trailing zero bytes  present only at v5
#
# Downgrading v5 -> v3 reproduced each real v3 donor with zero unexplained bytes (the only
# remaining differences were the owner/key header, which is rewritten per channel anyway, and
# per-donor label text).
SCHEMA_CONST = {3: 464, 5: 424}
VARIANT_AT = 116
V5_TRAILER = 4


def retarget_version(raw: bytes, to_version: int) -> bytes:
    """Rewrite a slot record to another class version.

    Only v5 -> v3 is derivable: going up would have to invent the plugin-variant id, which
    selects the mono/stereo build, and a wrong one is worse than no donor.

    ⚠️ DERIVED, not observed. Verified against every plugin the library holds at both versions
    (Channel EQ, Compressor, Echo) — each reproduced with no unexplained structural bytes. It
    is still an inference for a plugin with no v3 counterpart to check against, so a project
    built this way must be opened in Logic before it is trusted.
    """
    from_version = struct.unpack_from("<H", raw, VER_OFF)[0]
    if from_version == to_version:
        return raw
    if not (from_version == 5 and to_version == 3):
        raise ValueError(f"cannot retarget a v{from_version} record to v{to_version}: only "
                         "v5 -> v3 is derivable (v3 carries no plugin-variant id to restore)")
    payload = raw[HEADER:]
    blocks = find_blocks(payload)
    if not blocks:
        raise ValueError("no parameter chunk: refusing to retarget an unrecognised record")
    idx, _type_id, n_floats = blocks[0]
    trailer = len(payload) - (idx + 12 + n_floats * 4)
    if trailer < V5_TRAILER:
        # Klopfgeist has no trailer at all and gained a parameter between versions (14 -> 15
        # floats). Where the 4 bytes are not slack, the delta is a PARAMETER and dropping them
        # would truncate the chunk while its count word still claimed the old length.
        raise ValueError(
            f"only {trailer} trailing byte(s) after the parameter chunk: this plugin's float "
            "count differs between versions, so the delta is not schema and cannot be derived")
    buf = bytearray(raw)
    struct.pack_into("<H", buf, VER_OFF, to_version)
    struct.pack_into("<I", buf, HEADER, SCHEMA_CONST[to_version])
    struct.pack_into("<H", buf, HEADER + VARIANT_AT, 0)
    return _fix_size(bytes(buf[:len(buf) - V5_TRAILER]))


def _fix_size(raw: bytes) -> bytes:
    """Rewrite the record's own payload-size field after a length change."""
    buf = bytearray(raw)
    struct.pack_into("<I", buf, 28, len(buf) - HEADER)
    return bytes(buf)


def donor_key(type_id: int, version: int) -> str:
    return f"{type_id}-v{version}"


def harvest_donors(data: bytes, library: Path, names: dict[int, str] | None = None,
                   start: int = 24) -> list[str]:
    """Store one slot record per (plugin, version) found in ``data``. Existing donors are kept.

    Returns the keys written. The first instance of a plugin wins — they are interchangeable as
    donors, since every parameter gets patched or replaced verbatim by the caller.
    """
    library = Path(library)
    library.mkdir(parents=True, exist_ok=True)
    manifest = _read_manifest(library)
    written = []
    for record in project_records(data, start):
        if record.tag != b"UCuA" or b"GAMETSPP" not in record.raw:
            continue
        blocks = find_blocks(record.raw[HEADER:])
        if not blocks:
            continue
        type_id = blocks[0][1]
        key = donor_key(type_id, record.ver)
        path = library / f"{key}{SUFFIX}"
        if path.exists():
            continue
        atomic_write_bytes(path, record.raw)
        manifest[key] = {"type": type_id, "version": record.ver,
                         "floats": blocks[0][2], "bytes": len(record.raw) - HEADER}
        if names and type_id in names:
            manifest[key]["plugin"] = names[type_id]
        written.append(key)
    if written:
        atomic_write_json(library / MANIFEST, manifest, sort_keys=True, ensure_ascii=True)
    return sorted(written)


def load_donor_library(library: Path) -> dict[str, tuple[bytes, int, int]]:
    """key -> (record, plugin type id, class version)."""
    library = Path(library)
    if not library.is_dir():
        return {}
    out = {}
    for path in sorted(library.glob(f"*{SUFFIX}")):
        raw = path.read_bytes()
        blocks = find_blocks(raw[HEADER:])
        if not blocks:
            continue
        out[path.stem] = (raw, blocks[0][1], struct.unpack_from("<H", raw, VER_OFF)[0])
    return out


def _read_manifest(library: Path) -> dict:
    path = library / MANIFEST
    return json.loads(path.read_text()) if path.exists() else {}
