"""GAMETSPP binary primitives — find / read / patch Logic native-plugin float blocks.

Chunk layout (verified against Logic-written .cst, .pst and ProjectData):

    u32 total_size | u32 version | u32 n_floats | "GAMETSPP" | u32 plugin_type_id | float32 * n

``total_size`` counts from its own offset and equals ``24 + n*4`` (some chunks add a small
trailer). The u32 *after* the tag is a plugin **type id**, not a byte size — Limiter 199,
Channel EQ 236, Compressor 154, Enveloper 157, Gain 183. Treating it as a size over-reports
every block (a 13-float Limiter reads as 49) and runs past the chunk into the next slot.
"""

from __future__ import annotations

import re
import struct

GAMETSPP = b"GAMETSPP"
FLOAT_OFFSET = 12   # tag (8) + type id (4)
_PRE_HEADER = 12    # total_size + version + n_floats, immediately before the tag
_OVERHEAD = _PRE_HEADER + FLOAT_OFFSET


def _float_count(data: bytes, idx: int) -> int:
    """Float count for the chunk whose tag starts at ``idx``.

    Prefers the chunk's own count word, accepted only when it is self-consistent with
    ``total_size`` and actually present in the buffer; otherwise falls back to whatever
    remains (which keeps truncated//synthetic blocks readable rather than raising).
    """
    avail = max(0, (len(data) - (idx + FLOAT_OFFSET)) // 4)
    if idx >= _PRE_HEADER:
        total, _version, n = struct.unpack_from("<III", data, idx - _PRE_HEADER)
        if 0 <= n <= avail and total >= _OVERHEAD + n * 4:
            return n
    return avail


def find_blocks(data: bytes) -> list[tuple[int, int, int]]:
    """Return ``[(idx, plugin_type_id, n_floats)]`` for every GAMETSPP chunk."""
    blocks, pos = [], 0
    while True:
        idx = data.find(GAMETSPP, pos)
        if idx == -1:
            break
        pos = idx + 1
        type_id = struct.unpack_from("<I", data, idx + 8)[0] if idx + FLOAT_OFFSET <= len(data) else 0
        blocks.append((idx, type_id, _float_count(data, idx)))
    return blocks


def read_block_floats(data: bytes, idx: int, n: int) -> list[float]:
    return list(struct.unpack_from(f"<{n}f", data, idx + FLOAT_OFFSET))


def patch_block_floats(buf: bytearray, idx: int, offset: int, vals) -> None:
    packed = struct.pack(f"<{len(vals)}f", *vals)
    start = idx + FLOAT_OFFSET + offset * 4
    buf[start:start + len(packed)] = packed


# Logic writes a slot as: UCuA tag, "<preset>.pst", the plugin name, then the GAMETSPP block.
# So the plugin name is the last meaningful ASCII token before the block. Matching whole tokens
# (not substrings) keeps a Compressor's "Auto Gain" text from identifying the block as Gain.
_NATIVE = {
    "ChanEQ": "Channel EQ", "Channel EQ": "Channel EQ",
    "Compressor": "Compressor",
    "Enveloper": "Enveloper",
    "Gain": "Gain",
    "Limiter": "Limiter",
    "Adaptive Limiter": "Adaptive Limiter",
}
_TOKEN = re.compile(r"[\x20-\x7e]{2,}")


def _is_scaffolding(tok: str) -> bool:
    return tok.startswith("GAME") or tok == "UCuA" or tok.endswith(".pst")


def identify_plugin(data: bytes, idx: int) -> str:
    """Native plugin name for the GAMETSPP block at ``idx``, else ``"Unknown"``.

    A Logic re-save's paired copy of a block sits beyond the name, so it reads Unknown —
    which is what lets the patcher recognise and update copies (see services/spec.py).
    """
    # stop short of the 12-byte chunk pre-header: its size/count words can carry a printable
    # byte that would glue onto the name ("Compressor" + 0x50 -> "Compressor P").
    ctx = data[max(0, idx - 220):max(0, idx - _PRE_HEADER)].decode("latin-1", errors="replace")
    for tok in reversed(_TOKEN.findall(ctx)):
        tok = tok.strip()
        if _is_scaffolding(tok):
            continue
        return _NATIVE.get(tok, "Unknown")
    return "Unknown"
