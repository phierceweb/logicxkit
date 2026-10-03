"""The record stream of a `ProjectData` file: a 24-byte file header, then records to the end
of the file — a 36-byte record header (tag at +0, class version at +4, owner at +14, key at +18,
payload size at +28) and the payload. The stream carries no offset table, record count or
checksum, so a length change rewrites the file header's total at 0x10 and nothing else."""

from __future__ import annotations

import struct
from dataclasses import dataclass

HEADER = 36
VER_OFF, OWNER_OFF, KEY_OFF, SIZE_OFF = 4, 14, 18, 28
TOTAL_AT = 0x10        # file header: uint32 == filesize - 24
BODY_START = 24
NO_KEY = 0xFFFF


@dataclass(frozen=True)
class ProjRecord:
    tag: bytes
    ver: int
    owner: int
    key: int
    raw: bytes


def project_records(data: bytes, start: int = BODY_START) -> list[ProjRecord]:
    """Walk a record stream. Accepts any 4-byte tag — a project uses many.

    ``start`` is the 24-byte ProjectData file header by default; a .cst begins at 0.
    """
    out, pos = [], start
    while pos + HEADER <= len(data):
        size = struct.unpack_from("<I", data, pos + SIZE_OFF)[0]
        end = pos + HEADER + size
        if end > len(data):
            break
        out.append(ProjRecord(
            data[pos:pos + 4],
            struct.unpack_from("<H", data, pos + VER_OFF)[0],
            struct.unpack_from("<H", data, pos + OWNER_OFF)[0],
            struct.unpack_from("<H", data, pos + KEY_OFF)[0],
            data[pos:end]))
        pos = end
    return out


def reassemble(data: bytes, records: list[bytes]) -> bytes:
    """``data``'s file header over a new record stream, the total at 0x10 rewritten."""
    body = b"".join(records)
    head = bytearray(data[:BODY_START])
    struct.pack_into("<I", head, TOTAL_AT, len(body))
    return bytes(head) + body
