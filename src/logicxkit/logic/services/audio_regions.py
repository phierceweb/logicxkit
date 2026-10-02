"""Audio files and the regions that play them, read from Logic's imports and edits on blank-born
projects (2026-09-13/15, the public `audio-*` and `regions-a*` goldens).

An import adds an `lFuA` file record and a `gRuA` region record before the first `lytS`, both
carrying the same slot word in their header (+10), and an 80-byte entry of type 0x24 in the song
container (`regions.py`) whose `+44` word is that slot. A split adds a second region record with
the same slot and the piece's number in the header owner (+14), and an entry with that number
at `+40`; entry `(+44, +40)` pairs with record `(slot, owner)` on every project on hand with
audio, and the file is the record with the entry's slot.

The file record: `+8` u16 the name's length in UTF-16 units, `+10` the name (UTF-16 LE), then
`LFUA`; from that magic, `+138` the Media folder's path in a 256-byte NUL-padded buffer, `+406`
u32 file size, `+456` the format as a reversed four-CC (`EVAW`), `+464` u32 data offset, `+468`
u32 frames, `+476` u32 sample rate, `+480` u16 channels, `+482` u16 bits, `+508` u32 the number of
region records on the file (Logic loads that many: a split's second piece with the count left at
1 was dropped) — the file as Logic stored it, converted to the project's rate. The region record: `+5` bit 1 Mute, `+6` u32 the
region's first frame within the file, `+22` u32 its length in frames, `+74` the name (u16 byte
length, UTF-8, padded to even). The entry: `+12` bit 0 Mute, `+13` bit 1 Loop, `+28` the loop
length, `+64`..`+79` the fades (`fades.py`).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from .events import BAR_ONE, PPQ
from .fades import Fade, read_fade
from .region_params import REGION_COLOUR_AT, RegionParams, read_params
from .stream import HEADER, OWNER_OFF, project_records
from .midi import ENTRY_TICK_AT, LOOP_BIT, MUTE_BIT, REGION_BAR_ONE, entry_flags
from .recbuild import slot_of
from .regions import ENTRY, TAIL, TRACK_OBJECT_AT, TRACK_ROW_AT, entry_offsets, song_container
from .sequence import sequences
from .stacks import read_tracks
from .tracklist import arrange_run

FILE_TAG, REGION_TAG = b"lFuA", b"gRuA"
AUDIO_ENTRY = 0x24
ENTRY_PIECE_AT, ENTRY_ORDINAL_AT = 40, 44
NAME_COUNT_AT, NAME_AT = 8, 10
PATH_AT, SIZE_AT, FORMAT_AT, OFFSET_AT, FRAMES_AT, RATE_AT, CHANNELS_AT, BITS_AT = 138, 406, 456, 464, 468, 476, 480, 482
REGION_COUNT_AT = 508                        # u32 from the magic: the file's region records — Logic loads that many
REGION_MUTE_AT, REGION_MUTE_BIT = 5, 0x02
REGION_OFFSET_AT, REGION_FRAMES_AT, REGION_NAME_AT = 6, 22, 74


@dataclass(frozen=True)
class AudioFile:
    name: str
    folder: str
    size: int
    format: str
    data_offset: int
    frames: int
    rate: int
    channels: int
    bits: int


@dataclass(frozen=True)
class AudioRegion:
    track: str
    row: int
    name: str
    start: int                 # absolute tick, bar 1 at 38400
    frames: int
    file: AudioFile | None
    offset: int = 0            # the region's first frame within its file
    object_id: int = 0         # the track object the entry names
    muted: bool = False
    loop: bool = False
    piece: int = 0             # 0, or the piece number of a split
    fade: Fade = Fade()
    at: int = -1               # its entry's offset in the song container
    record: int = -1           # its region record's index
    file_slot: int = -1        # the slot word its record and file carry
    params: RegionParams = RegionParams()
    colour: int = 0            # a palette index; a region born on a track carries the track's

    @property
    def start_bar(self) -> float:
        return (self.start - BAR_ONE) / (PPQ * 4) + 1

    @property
    def record_key(self) -> tuple[int, int]:
        """(slot, piece): the pair that names its record, the same across every edit."""
        return (self.file_slot, self.piece)


def name_count(payload: bytes) -> int:
    return struct.unpack_from("<H", payload, NAME_COUNT_AT)[0]


def magic_at(payload: bytes) -> int:
    """Offset of an `lFuA` payload's `LFUA` magic, past the UTF-16 name."""
    return NAME_AT + 2 * name_count(payload)


def file_name(payload: bytes) -> str:
    return payload[NAME_AT:magic_at(payload)].decode("utf-16-le", "replace")


def _file(payload: bytes) -> AudioFile:
    m = magic_at(payload)
    folder = payload[m + PATH_AT:m + FORMAT_AT].split(b"\0", 1)[0].decode("utf-8", "replace")
    u32 = lambda at: struct.unpack_from("<I", payload, m + at)[0]  # noqa: E731
    u16 = lambda at: struct.unpack_from("<H", payload, m + at)[0]  # noqa: E731
    return AudioFile(file_name(payload), folder, u32(SIZE_AT), payload[m + FORMAT_AT:m + FORMAT_AT + 4][::-1].decode("latin-1"),
                     u32(OFFSET_AT), u32(FRAMES_AT), u32(RATE_AT), u16(CHANNELS_AT), u16(BITS_AT))


def read_audio_files(data: bytes) -> list[AudioFile]:
    return [_file(r.raw[HEADER:]) for r in project_records(data) if r.tag == FILE_TAG]


def files_by_slot(records) -> dict[int, AudioFile]:
    return {slot_of(r.raw): _file(r.raw[HEADER:]) for r in records if r.tag == FILE_TAG}


def region_name(payload: bytes) -> str:
    n = struct.unpack_from("<H", payload, REGION_NAME_AT)[0]
    return payload[REGION_NAME_AT + 2:REGION_NAME_AT + 2 + n].decode("utf-8", "replace")


def region_key(raw: bytes) -> tuple[int, int]:
    """A region record's ``(slot, piece)``, the pair its entry names."""
    return slot_of(raw), struct.unpack_from("<H", raw, OWNER_OFF)[0]


def entry_pair(entry: bytes) -> tuple[int, int]:
    """An audio entry's ``(slot, piece)``: its `+44` word and `+40` byte."""
    return struct.unpack_from("<I", entry, ENTRY_ORDINAL_AT)[0], entry[ENTRY_PIECE_AT]


def region_records(records) -> dict[tuple[int, int], int]:
    """``(slot, piece)`` -> index of the region record."""
    return {region_key(r.raw): i for i, r in enumerate(records) if r.tag == REGION_TAG}


def audio_entry_pairs(records) -> list[tuple[int, int]]:
    """``(slot, piece)`` of every audio entry in every sequence (take folders included)."""
    pairs = []
    for t in sequences(records):
        events = records[t.end].raw[HEADER:]
        if len(events) < ENTRY + TAIL:
            continue
        for off in entry_offsets(events):
            if struct.unpack_from("<H", events, off)[0] == AUDIO_ENTRY:
                pairs.append(entry_pair(events[off:off + ENTRY]))
    return pairs


def audio_entry_words(records) -> list[int]:
    """The `+44` word of every audio entry in every sequence."""
    return [slot for slot, _piece in audio_entry_pairs(records)]


def read_audio_regions(data: bytes, track_count: int | None = None) -> list[AudioRegion]:
    """Every audio region in the song container's order, with the record and file its entry names."""
    records = project_records(data)
    run = arrange_run(records, track_count)
    song = song_container(records, run)
    if song is None:
        return []
    names = {r["object_id"]: r["name"] for r in read_tracks(data, track_count)}
    files, by_key = files_by_slot(records), region_records(records)
    payload = records[song.end].raw[HEADER:]
    out = []
    for off in entry_offsets(payload):
        e = payload[off:off + ENTRY]
        if struct.unpack_from("<H", e, 0)[0] != AUDIO_ENTRY:
            continue
        slot, piece = entry_pair(e)
        k = by_key.get((slot, piece))
        if k is None:
            continue
        rec = records[k].raw[HEADER:]
        oid = struct.unpack_from("<H", e, TRACK_OBJECT_AT)[0]
        flags = entry_flags(e)
        out.append(AudioRegion(names.get(oid, f"object {oid}"), struct.unpack_from("<H", e, TRACK_ROW_AT)[0], region_name(rec),
                               struct.unpack_from("<I", e, ENTRY_TICK_AT)[0] - REGION_BAR_ONE + BAR_ONE,
                               struct.unpack_from("<I", rec, REGION_FRAMES_AT)[0], files.get(slot),
                               struct.unpack_from("<I", rec, REGION_OFFSET_AT)[0], oid,
                               bool(flags & MUTE_BIT), bool(flags & LOOP_BIT), piece, read_fade(e), off, k, slot,
                               read_params(e), rec[REGION_COLOUR_AT]))
    return out
