"""A WAV's sample layout and data chunk, for the readers that decode it (`onsets.read_wav`
decodes every sample, `silence.peak_envelope` a peak per hop). PCM or IEEE float; an extensible
fmt resolves through its SubFormat GUID. Logic pads no chunk after ``data``, so odd sizes are
stepped over by content, not by the RIFF rule."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

PCM, IEEE_FLOAT, EXTENSIBLE = 0x0001, 0x0003, 0xFFFE
FMT_BASIC, FMT_EXTENSIBLE = 16, 40
CB_SIZE_AT, SUBFORMAT_AT, EXTENSION = 16, 24, 22
GUID_TAIL = bytes.fromhex("000000001000800000aa00389b71")      # KSDATAFORMAT_SUBTYPE_* after its code


@dataclass(frozen=True)
class WavData:
    code: int                  # PCM or IEEE_FLOAT
    channels: int
    rate: int
    bits: int
    block: int                 # bytes per frame
    data: bytes

    @property
    def frames(self) -> int:
        return len(self.data) // self.block

    @property
    def kind(self) -> str:
        return "float" if self.code == IEEE_FLOAT else "PCM"


def _format_code(path: Path, fmt: bytes) -> int:
    code = struct.unpack_from("<H", fmt, 0)[0]
    if code in (PCM, IEEE_FLOAT):
        return code
    if code != EXTENSIBLE:
        raise ValueError(f"{path}: WAV format code 0x{code:04x} is not PCM or IEEE float")
    cb = struct.unpack_from("<H", fmt, CB_SIZE_AT)[0] if len(fmt) >= CB_SIZE_AT + 2 else 0
    if len(fmt) < FMT_EXTENSIBLE or cb < EXTENSION:
        raise ValueError(f"{path}: WAVE_FORMAT_EXTENSIBLE with a {len(fmt)}-byte fmt chunk and cbSize {cb}")
    guid = fmt[SUBFORMAT_AT:SUBFORMAT_AT + 16]
    if guid[2:] != GUID_TAIL:
        raise ValueError(f"{path}: WAVE_FORMAT_EXTENSIBLE SubFormat GUID {guid.hex()} is not a KSDATAFORMAT_SUBTYPE")
    code = struct.unpack_from("<H", guid, 0)[0]
    if code not in (PCM, IEEE_FLOAT):
        raise ValueError(f"{path}: WAVE_FORMAT_EXTENSIBLE SubFormat 0x{code:04x} is not PCM or IEEE float")
    return code


def wav_data(path: Path) -> WavData:
    b = Path(path).read_bytes()
    k, fmt, data = 12, None, None
    while k + 8 <= len(b):
        if not all(32 <= c < 127 for c in b[k:k + 4]):
            k += 1                                  # a pad byte after an odd chunk
            if k + 8 > len(b):
                break
        tag, n = b[k:k + 4], struct.unpack_from("<I", b, k + 4)[0]
        if not all(32 <= c < 127 for c in tag):
            break
        if k + 8 + n > len(b):
            if tag == b"data":
                raise ValueError(f"{path}: the data chunk claims {n} bytes but the file ends {k + 8 + n - len(b)} bytes short")
            break
        if tag == b"fmt ":
            fmt = b[k + 8:k + 8 + n]
        elif tag == b"data":
            data = b[k + 8:k + 8 + n]
            break
        k += 8 + n
    if fmt is None or data is None or len(fmt) < FMT_BASIC:
        raise ValueError(f"{path}: not a WAV with a fmt and a data chunk")
    code = _format_code(path, fmt)
    _code, channels, rate, _bps, block, bits = struct.unpack_from("<HHIIHH", fmt, 0)
    if not channels or not bits or block != channels * bits // 8:
        raise ValueError(f"{path}: {bits}-bit, {channels} channel(s) in {block}-byte frames is not a WAV layout this reads")
    return WavData(code, channels, rate, bits, block, data)
