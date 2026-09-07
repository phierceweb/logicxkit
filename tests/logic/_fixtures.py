"""Shared synthetic GAMETSPP fixtures, faithful to the real chunk container.

    u32 total_size | u32 version | u32 n_floats | "GAMETSPP" | u32 plugin_type_id | float32 * n

Fixtures must carry the 12-byte pre-header: without it `identify_plugin` and `find_blocks`
are exercised against a shape Logic never writes.
"""

import struct

CHUNK_OVERHEAD = 24

# type ids as Logic writes them
TYPE_ID = {"ChanEQ": 236, "Compressor": 154, "Enveloper": 157, "Gain": 183, "Limiter": 199}


def chunk(type_id: int, floats: list[float], trailer: bytes = b"") -> bytes:
    body = struct.pack(f"<{len(floats)}f", *floats)
    return (struct.pack("<III", CHUNK_OVERHEAD + len(floats) * 4, 1, len(floats))
            + b"GAMETSPP" + struct.pack("<I", type_id) + body + trailer)


def block(label: str, n_floats: int) -> bytes:
    """A plugin region: ASCII name, then its chunk — as a real slot is laid out."""
    return (label + " ").encode("latin-1") + chunk(TYPE_ID.get(label.strip(), 0),
                                                   [0.0] * n_floats)
