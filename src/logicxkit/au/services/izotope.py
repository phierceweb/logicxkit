"""iZotope's AU state (Neutron 5, and its siblings): the ``data`` blob is a 16-byte header —
magic 0x0080fb83, a version, the compressed length, the decompressed length — then zlib over a
JSON document of typed values (``{"Type": "Float", "Value": 20.5}``) whose parameters sit under
``DSP State/Value/DSP Elements/Value/<Module>/Value/<Parameter>`` in real units."""

from __future__ import annotations

import json
import struct
import zlib

MAGIC = 0x0080FB83
HEADER = 16


class IzotopeError(ValueError):
    """Not an iZotope state blob."""


def parse_izotope(blob: bytes) -> dict:
    """The JSON document inside the blob."""
    if len(blob) < HEADER:
        raise IzotopeError("too short for an iZotope state header")
    magic, _version, _packed, plain = struct.unpack_from("<IIII", blob, 0)
    if magic != MAGIC:
        raise IzotopeError(f"magic {magic:#x} is not iZotope's {MAGIC:#x}")
    try:
        raw = zlib.decompress(blob[HEADER:])
    except zlib.error as e:
        raise IzotopeError(f"the state does not inflate: {e}") from None
    if plain and len(raw) != plain:
        raise IzotopeError(f"inflated to {len(raw)} bytes, the header says {plain}")
    return json.loads(raw.decode("utf-8"))


def dsp_values(doc: dict) -> dict[str, float | bool | int | str]:
    """Every scalar parameter of every DSP element, keyed ``Module/Parameter``."""
    out: dict[str, float | bool | int | str] = {}
    elements = doc.get("DSP State", {}).get("Value", {}).get("DSP Elements", {}).get("Value", {})
    for module, entry in elements.items():
        for name, node in entry.get("Value", {}).items():
            if isinstance(node, dict) and "Value" in node and not isinstance(node["Value"], (dict, list)):
                out[f"{module}/{name}"] = node["Value"]
    return out


def pack_izotope(doc: dict, version: int = 1) -> bytes:
    """A state blob from the document, as the plug-in lays it out."""
    raw = json.dumps(doc, indent=3).encode("utf-8")
    packed = zlib.compress(raw)
    return struct.pack("<IIII", MAGIC, version, len(packed), len(raw)) + packed
