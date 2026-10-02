"""Write an audio region from a WAV, as Logic's File > Import > Audio File does (2026-09-13,
`audio_regions.py` has the layouts): the file copied into the bundle's `Media/Audio Files`, an
`lFuA` record and a `gRuA` record after the project's last ones (before the first `lytS` on a
project without), a type-0x24 entry in the song container and a kind-0x0b registry pair. The
records are Logic's own (packaged `audio-region-12.3.1.json`) with the measured fields
re-stamped; the file must already be at the project's sample rate, since Logic converts on
import and this does not.

Logic's imports onto a blank-born project number n regions densely: the k-th file and region
records carry slot word 4k in their headers, the entries' `+44` words are 0, 4, ... 4(n-1), each
file record's `ord` is k+1 and its `link` the next file's word (the last's `LAST_LINK`), and each
registry run holds one 0x0b entry per word. The next import extends that layout; a project in any
other is refused. The import is also the only current file record, current region record and
selected song-container entry; the region's time at `+42` keeps the template's distance from its
UUID's timestamp.
"""

from __future__ import annotations

import json
import shutil
import struct
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from ...utils.data import data_file
from .audio_regions import (
    BITS_AT,
    CHANNELS_AT,
    ENTRY_ORDINAL_AT,
    FILE_TAG,
    FORMAT_AT,
    FRAMES_AT,
    NAME_AT,
    NAME_COUNT_AT,
    OFFSET_AT,
    PATH_AT,
    RATE_AT,
    REGION_COUNT_AT,
    REGION_FRAMES_AT,
    REGION_NAME_AT,
    REGION_TAG,
    SIZE_AT,
    audio_entry_words,
    magic_at,
    read_audio_files,
)
from .stream import HEADER, project_records, reassemble
from .midi import ENTRY_TICK_AT
from .midi_write import _place_entry, _track, entry_tick
from .recbuild import fresh_uuid, rec, slot_of, time_fields, with_slot
from .regions import TRACK_OBJECT_AT, TRACK_ROW_AT, entry_offsets, song_container
from .registry import GNOS_TAG, TIME_STRIDE, UUID_STRIDE, run_entries
from .tracklist import arrange_run
from .validate import require_full_walk, require_valid

_DATA = "audio-region-12.3.1.json"
AUDIO_REGION_KIND = 0x0B
_NEIGHBOURS = (0x0A, 0x0C)
ORDINAL_AT, LINK_AT = FORMAT_AT + 56, FORMAT_AT + 62         # u32s from the format four-CC
LAST_LINK = 0xFFFFFFFF
FOLDER_LEN = 256
FILE_CURRENT_AT, FILE_CHANNELS_AT = 7, 400                   # u8s from the LFUA magic
MAX_NAME_UNITS = 0xFFFF
REGION_UUID_FROM_END = 47
REGION_CURRENT_AT, REGION_TIME_AT = 38, 42
ENTRY_SELECTED_AT, SELECTED = 15, 0x80
UNMEASURED = ("the project's audio regions are not in the layout Logic's own imports were measured on "
              "(file records, region records and entries numbered 0, 4, 8, ... in file order); import it in Logic")


@dataclass(frozen=True)
class WavInfo:
    size: int
    format: str
    data_offset: int
    frames: int
    rate: int
    channels: int
    bits: int


def wav_info(path: Path) -> WavInfo:
    """A PCM WAV's header facts, walking its RIFF chunks."""
    raw = Path(path).read_bytes()
    if raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
        raise ValueError(f"{path}: not a RIFF WAVE file")
    pos, fmt, data_at, data_len = 12, None, None, None
    while pos + 8 <= len(raw):
        tag, size = raw[pos:pos + 4], struct.unpack_from("<I", raw, pos + 4)[0]
        if tag == b"fmt ":
            fmt = struct.unpack_from("<HHIIHH", raw, pos + 8)
        elif tag == b"data":
            data_at, data_len = pos + 8, size
            break
        pos += 8 + size + (size & 1)
    if fmt is None or data_at is None:
        raise ValueError(f"{path}: no fmt or data chunk")
    audio_format, channels, rate, _byte_rate, block_align, bits = fmt
    if audio_format != 1:
        raise ValueError(f"{path}: only PCM WAV is written (format tag {audio_format})")
    return WavInfo(len(raw), "WAVE", data_at, data_len // block_align, rate, channels, bits)


def import_templates() -> dict[str, bytes]:
    t = json.loads(data_file("logic", _DATA).read_text())
    return {role: bytes.fromhex(r.get("header", "")) + bytes.fromhex(r["payload"]) for role, r in t["records"].items()}


def _magic(raw: bytes) -> int:
    """Offset in ``raw`` of a file record's `LFUA` magic, past the UTF-16 name."""
    return HEADER + magic_at(raw[HEADER:])


def file_chain(raw: bytes) -> tuple[int, int]:
    """A file record's ``(ord, link)``."""
    m = _magic(raw)
    return struct.unpack_from("<I", raw, m + ORDINAL_AT)[0], struct.unpack_from("<I", raw, m + LINK_AT)[0]


def superseded(raw: bytes, *, link: int | None = None) -> bytes:
    """An existing file or region record no longer current; a file record relinked to ``link``."""
    body = bytearray(raw)
    if raw[:4] == FILE_TAG:
        body[_magic(raw) + FILE_CURRENT_AT] = 0
        if link is not None:
            struct.pack_into("<I", body, _magic(raw) + LINK_AT, link)
    else:
        body[HEADER + REGION_CURRENT_AT] = 0
    return bytes(body)


def file_record(template: bytes, *, name: str, folder: str, info: WavInfo, ordinal: int) -> bytes:
    """The ``ordinal``-th file record (0-based), the last of the chain. The name is UTF-16 LE
    with its unit count, as Logic's imports of `é`, `🥁` and `日本` names wrote."""
    p = template[HEADER:]
    encoded = name.encode("utf-16-le")
    if len(encoded) // 2 > MAX_NAME_UNITS:
        raise ValueError(f"a WAV's name is at most {MAX_NAME_UNITS} UTF-16 units")
    body = bytearray(p[:NAME_COUNT_AT] + struct.pack("<H", len(encoded) // 2) + encoded + p[magic_at(p):])
    m = NAME_AT + len(encoded)
    path_bytes = folder.encode("utf-8")
    if len(path_bytes) >= FOLDER_LEN:
        raise ValueError(f"the media folder's path is longer than the record holds: {folder}")
    body[m + PATH_AT:m + PATH_AT + FOLDER_LEN] = path_bytes.ljust(FOLDER_LEN, b"\0")
    body[m + FILE_CURRENT_AT] = 1
    body[m + FILE_CHANNELS_AT] = info.channels
    struct.pack_into("<I", body, m + SIZE_AT, info.size)
    body[m + FORMAT_AT:m + FORMAT_AT + 4] = info.format.encode("latin-1")[::-1]
    struct.pack_into("<I", body, m + OFFSET_AT, info.data_offset)
    struct.pack_into("<I", body, m + FRAMES_AT, info.frames)
    struct.pack_into("<I", body, m + RATE_AT, info.rate)
    struct.pack_into("<H", body, m + CHANNELS_AT, info.channels)
    struct.pack_into("<H", body, m + BITS_AT, info.bits)
    struct.pack_into("<I", body, m + ORDINAL_AT, ordinal + 1)
    struct.pack_into("<I", body, m + LINK_AT, LAST_LINK)
    struct.pack_into("<I", body, m + REGION_COUNT_AT, 1)
    return with_slot(rec(FILE_TAG, template, bytes(body)), 4 * ordinal)


def _uuid_time(uuid: bytes) -> int:
    return int.from_bytes(time_fields(uuid), "little")


def region_record(template: bytes, *, name: str, frames: int, ordinal: int) -> bytes:
    """The ``ordinal``-th region record; the name is UTF-8, padded to an even length."""
    p = template[HEADER:]
    old_uuid = p[len(p) - REGION_UUID_FROM_END:len(p) - REGION_UUID_FROM_END + 16]
    old_n = struct.unpack_from("<H", p, REGION_NAME_AT)[0]
    text = name.encode("utf-8")
    if len(text) > 0xFFFF:
        raise ValueError("a region's name is at most 65535 bytes of UTF-8")
    body = bytearray(p[:REGION_NAME_AT] + struct.pack("<H", len(text)) + text + bytes(len(text) % 2)
                     + p[REGION_NAME_AT + 2 + old_n + old_n % 2:])
    struct.pack_into("<I", body, REGION_FRAMES_AT, frames)
    body[REGION_CURRENT_AT] = 1
    end, uuid = len(body) - REGION_UUID_FROM_END, fresh_uuid()
    body[end:end + 16] = uuid
    time = struct.unpack_from("<Q", p, REGION_TIME_AT)[0] + _uuid_time(uuid) - _uuid_time(old_uuid)
    struct.pack_into("<Q", body, REGION_TIME_AT, time % 2**64)
    return with_slot(rec(REGION_TAG, template, bytes(body)), 4 * ordinal)


def _deselected(payload: bytes) -> bytes:
    body = bytearray(payload)
    for off in entry_offsets(payload):
        body[off + ENTRY_SELECTED_AT] &= ~SELECTED
    return bytes(body)


def _registered(g: bytes, stride: int) -> tuple[list[tuple[int, int]], int | None]:
    """``(offset, word)`` of the audio-region entries in the ``stride`` run — a single one sits
    between the 0x0a and 0x0c runs, too short for `run_entries` — and where the next one goes."""
    own = run_entries(g, AUDIO_REGION_KIND, stride)
    if not own:
        before, after = (run_entries(g, kind, stride) for kind in _NEIGHBOURS)
        if after:
            at, lone = after[0][0], after[0][0] - stride
        elif before:
            at = lone = before[-1][0] + stride
        else:
            return [], None
        if not (0 <= lone and lone + 8 <= len(g) and struct.unpack_from("<I", g, lone)[0] == AUDIO_REGION_KIND):
            return [], at
        own = [(lone, struct.unpack_from("<I", g, lone + 4)[0])]
    return own, own[-1][0] + stride


def _register(payload: bytes, *, word: int) -> bytes:
    """The kind-0x0b pair for ``word``, after the audio-region entries of each run."""
    g = bytearray(payload)
    uuid = fresh_uuid()
    for stride, tail in ((UUID_STRIDE, uuid), (TIME_STRIDE, time_fields(uuid))):
        at = _registered(g, stride)[1]
        if at is None:
            raise ValueError("gnoS: no audio-region registry run to extend")
        g[at:at] = struct.pack("<II", AUDIO_REGION_KIND, word) + tail
    return bytes(g)


def measured_count(records) -> int:
    """How many audio files the project holds, when they are laid out as Logic's own imports
    left them (the module docstring; a split's pieces share their file's slot); ValueError otherwise."""
    files = [r.raw for r in records if r.tag == FILE_TAG]
    g = next((r.raw[HEADER:] for r in records if r.tag == GNOS_TAG), b"")
    n = len(files)
    words = [4 * k for k in range(n)]
    chain = [(k + 1, 4 * (k + 1) if k + 1 < n else LAST_LINK) for k in range(n)]
    laid_out = (sorted(set(audio_entry_words(records))) == words
                and [slot_of(r) for r in files] == words
                and sorted({slot_of(r.raw) for r in records if r.tag == REGION_TAG}) == words
                and [file_chain(r) for r in files] == chain
                and all([w for _at, w in _registered(g, stride)[0]] == words for stride in (UUID_STRIDE, TIME_STRIDE)))
    if not laid_out:
        raise ValueError(UNMEASURED)
    return n


def add_audio_region(data: bytes, *, track: str, start: int, wav: Path, media_folder: Path,
                     name: str | None = None, rate: int | None = None,
                     track_count: int | None = None) -> tuple[bytes, dict]:
    """``wav`` copied into ``media_folder`` and placed on ``track`` from absolute tick
    ``start`` -> ``(project, {track, file, frames, ordinal, name})``. ``rate`` is the project's
    sample rate when known; a file at another rate is refused, and so is a project whose audio
    regions are not in the measured layout (`measured_count`)."""
    info = wav_info(wav)
    if rate is not None and info.rate != rate:
        raise ValueError(f"{Path(wav).name} is at {info.rate} Hz; the project runs at {rate} Hz and Logic would convert it")
    require_full_walk(data)
    records = project_records(data)
    object_id, row = _track(data, track, track_count)
    run = arrange_run(records, track_count)
    song = song_container(records, run)
    if song is None:
        raise ValueError("no song container to place the region in")
    ordinal = measured_count(records)
    t = import_templates()
    media_folder = Path(media_folder)
    target = media_folder / unicodedata.normalize("NFD", Path(wav).name)     # the form Logic's import keeps
    if target.exists() and target.read_bytes() != Path(wav).read_bytes():
        raise ValueError(f"{target} exists with other content")
    if any(f.name == target.name for f in read_audio_files(data)):
        raise ValueError(f"the project already holds an audio file named {target.name}; rename the WAV before importing it")
    file_rec = file_record(t["lfua"], name=target.name, folder=str(media_folder.resolve()), info=info, ordinal=ordinal)
    region_name = name or target.stem
    region_rec = region_record(t["grua"], name=region_name, frames=info.frames, ordinal=ordinal)
    entry = bytearray(t["entry"])
    struct.pack_into("<I", entry, ENTRY_TICK_AT, entry_tick(start))
    struct.pack_into("<H", entry, TRACK_OBJECT_AT, object_id)
    struct.pack_into("<H", entry, TRACK_ROW_AT, row)
    struct.pack_into("<I", entry, ENTRY_ORDINAL_AT, 4 * ordinal)
    entry[ENTRY_SELECTED_AT] |= SELECTED
    last_file = max((i for i, r in enumerate(records) if r.tag == FILE_TAG), default=None)
    last_region = max((i for i, r in enumerate(records) if r.tag in (FILE_TAG, REGION_TAG)), default=None)
    anchor = last_region if last_region is not None else next(i for i, r in enumerate(records) if r.tag == b"lytS") - 1
    out = []
    for i, r in enumerate(records):
        raw = r.raw
        if i == song.end:
            raw = rec(b"qSvE", raw, _place_entry(_deselected(raw[HEADER:]), bytes(entry)))
        elif r.tag == GNOS_TAG:
            raw = rec(GNOS_TAG, raw, _register(raw[HEADER:], word=4 * ordinal))
        elif r.tag in (FILE_TAG, REGION_TAG):
            raw = superseded(raw, link=4 * ordinal if i == last_file else None)
        out.append(raw)
        if i == anchor:
            out += [file_rec, region_rec]
    result = reassemble(data, out)
    require_valid(result)
    media_folder.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(wav, target)
    return result, {"track": track, "file": target.name, "frames": info.frames, "ordinal": ordinal, "name": region_name}
