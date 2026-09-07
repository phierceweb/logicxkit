"""FabFilter ``.ffp`` preset files.

Layout (verified against Pro-C 2 / Pro-L / Pro-MB / Pro-Q 2 factory presets):
4CC magic (``FC2p``, ``FPLr``, ``FPMb``, …) + u32 LE version + u32 LE param
count + count × float32 LE. Param position i corresponds to AU parameter id i
of the same plugin, so the AU parameter table names every value.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

_MAX_PARAMS = 8192  # sanity bound: real plugins top out in the hundreds


class FfpError(ValueError):
    """Not a parseable .ffp file."""


@dataclass(frozen=True)
class FfpPreset:
    magic: str
    version: int
    values: tuple[float, ...]


def parse_ffp(data: bytes) -> FfpPreset:
    if len(data) < 12:
        raise FfpError("too short for an .ffp header")
    magic = data[:4]
    if not all(32 <= b < 127 for b in magic):
        raise FfpError(f"implausible magic {magic!r}")
    version, count = struct.unpack_from("<II", data, 4)
    if count > _MAX_PARAMS:
        raise FfpError(f"implausible param count {count}")
    need = 12 + 4 * count
    if len(data) < need:
        raise FfpError(f"truncated value table: need {need}B, have {len(data)}B")
    values = struct.unpack_from(f"<{count}f", data, 12)
    return FfpPreset(magic.decode("ascii"), version, values)
