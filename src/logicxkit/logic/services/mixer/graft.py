"""Graft — splice one strip's routing header onto another's plugin-slot region.

A `.cst` is two independent layers: an `OCuA` header (routing — output bus, sends, fader,
channel identity) and a slot region (the plugin chain). Neither is synthesisable, but both
are *transplantable*: taking a target channel's header and a donor's slots yields a strip
with the target's routing and the donor's chain shape. That is how we build chain shapes no
single saved strip has, without inheriting the donor's routing.

Header words (uint32 LE): w7 @0x1c = header length (slots begin at w7 + SEAM_PAD);
w10 @0x28 = channel number in the high bytes, type flag in the low byte.
"""

from __future__ import annotations

import re
import struct

OCUA = b"OCuA"
W_HEADER_LEN = 28  # w7
W_CHANNEL = 40     # w10
SEAM_PAD = 0x24
# low byte of w10 — verified against a whole strip library (the folder is ground truth)
_KINDS = {0x40: "track", 0x42: "bus", 0x43: "instrument", 0x4C: "output"}


def _require_strip(data: bytes) -> None:
    if not data.startswith(OCUA):
        raise ValueError("not a .cst: missing OCuA magic")
    if len(data) < W_CHANNEL + 4:
        raise ValueError("truncated .cst: no header words")


def seam(data: bytes) -> int:
    """Byte offset where the plugin-slot region begins."""
    _require_strip(data)
    off = struct.unpack_from("<I", data, W_HEADER_LEN)[0] + SEAM_PAD
    if not 0 < off <= len(data):
        raise ValueError(f"implausible seam {off} for {len(data)}-byte strip")
    return off


def channel_info(data: bytes) -> dict:
    """Channel identity from the header: {'number': int, 'kind': track|bus|unknown, 'raw': int}."""
    _require_strip(data)
    word = struct.unpack_from("<I", data, W_CHANNEL)[0]
    return {"number": word >> 16, "kind": _KINDS.get(word & 0xFF, "unknown"), "raw": word}


def graft(target: bytes, donor: bytes) -> bytes:
    """Target's routing header + donor's plugin-slot region."""
    return target[:seam(target)] + donor[seam(donor):]


# Slot preset labels ("<name>.pst") sit in fixed-width null-padded fields — measured at 67 bytes
# across every strip in the library — so they can be rewritten without changing file length.
LABEL_FIELD = 67
# null-anchored on both sides: the field is null-padded, so an unanchored match can swallow a
# printable byte of the preceding binary struct into the name.
_LABEL_RE = re.compile(rb"(?<=\x00)[\x20-\x7e]{1,63}\.pst")


def preset_labels(data: bytes) -> list[tuple[int, str]]:
    """[(offset, "<name>.pst")] for each plugin slot's preset label."""
    return [(m.start(), m.group().decode("latin-1"))
            for m in _LABEL_RE.finditer(data)
            if data[m.end():m.end() + 1] == b"\x00"]


def relabel_presets(data: bytes, name: str) -> bytes:
    """Rewrite every slot's preset label to ``name``, in place (length unchanged).

    A grafted strip otherwise carries the donor's labels, which misdescribe it in Logic's UI.
    """
    field = f"{name}.pst".encode("latin-1")
    if len(field) > LABEL_FIELD:
        raise ValueError(f"label '{name}.pst' exceeds the {LABEL_FIELD}-byte field")
    buf = bytearray(data)
    for off, _ in preset_labels(data):
        buf[off:off + LABEL_FIELD] = field.ljust(LABEL_FIELD, b"\x00")
    return bytes(buf)


# A strip records its own identity in a UCuA record: a 64-byte null-padded filename at
# tag+52, immediately followed by a 64-byte category (its folder). Clones and grafts inherit
# the donor's, so the built file claims to be a different strip.
PROV_NAME_OFF = 52
PROV_FIELD = 64
_CST_NAME = re.compile(rb"(?<=\x00)[\x20-\x7e]{1,60}\.cst")


def provenance(data: bytes) -> list[tuple[int, str, str]]:
    """[(name_offset, name, category)] for each self-identifying record."""
    out = []
    for m in _CST_NAME.finditer(data):
        start = m.start()
        if data.rfind(b"UCuA", 0, start) != start - PROV_NAME_OFF:
            continue
        fields = [data[start + i * PROV_FIELD: start + (i + 1) * PROV_FIELD].split(b"\x00")[0]
                  for i in (0, 1)]
        out.append((start, fields[0].decode("latin-1"), fields[1].decode("latin-1")))
    return out


def set_provenance(data: bytes, name: str, category: str) -> bytes:
    """Rewrite the strip's own name + category in place (length unchanged)."""
    encoded = [name.encode("latin-1"), category.encode("latin-1")]
    for field in encoded:
        if len(field) > PROV_FIELD:
            raise ValueError(f"'{field.decode()}' exceeds the {PROV_FIELD}-byte field")
    buf = bytearray(data)
    for start, _n, _c in provenance(data):
        for i, field in enumerate(encoded):
            at = start + i * PROV_FIELD
            buf[at:at + PROV_FIELD] = field.ljust(PROV_FIELD, b"\x00")
    return bytes(buf)
