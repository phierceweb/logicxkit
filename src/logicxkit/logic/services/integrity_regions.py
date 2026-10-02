"""The write gate's region checks, over the song container (`regions.py`).

An entry is the same region across a write when its track object, tick and type match: row
writers renumber `+20`, the audio and quantize writers re-flag `+13`/`+15`/`+32`/`+48`, none of
them moves those three; a writer that moves or splits a region names the keys it moves. An
audio entry pairs with its region record by (`+44` slot, `+40` piece) and with its file by slot
(`audio_regions.py`); Logic's own projects keep region records no entry names, so the pairing
is held as counts that must not grow, not as a bijection.

What an entry carries is held across the write too, per entry: the file it plays, the place its
`+32` slot or audio `+44` slot names, and whether its flex marker blocks are still there.
Quantize writes, and re-writes, the blocks of audio entries, so only a flexed entry losing all
of them, or a MIDI entry gaining any, is refused; so is a hit whose target does not rise past
the previous hit's, or an RBA Sequence triple left with no entry naming it.
"""

from __future__ import annotations

import struct
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from operator import attrgetter
from typing import NamedTuple

from .audio_regions import (
    AUDIO_ENTRY, FILE_TAG, REGION_TAG, audio_entry_pairs, entry_pair, file_name, region_key,
)
from .events import BAR_ONE
from .flexmarkers import HIT, KIND_AT, OFF, block_fields, rba_sequences
from .stream import HEADER
from .midi import ENTRY_SLOT_AT, ENTRY_TICK_AT, MIDI_ENTRY, REGION_BAR_ONE
from .recbuild import slot_of
from .regions import (
    ENTRY, MARKER_BYTE, MARKER_BYTES_AT, MARKER_KIND, MARKER_KIND_AT, TAIL, TRACK_OBJECT_AT, entry_blocks, song_events,
)
from .registry import GNOS_TAG, SLOT_TYPE, TIME_STRIDE, UUID_STRIDE, run_entries
from .sequence import sequences

RegionKey = tuple[int, int, int]              # (track object, absolute tick, entry type)
NO_SLOT = 0xFFFFFFFF                          # an entry with no sequence of its own


class Placed(NamedTuple):
    key: RegionKey
    blocks: int                               # flex marker blocks after the entry
    slot: int | None                          # `+32`, unless NO_SLOT
    counter: int | None                       # an audio entry's `+44` slot word
    file: str | None                          # the file that slot names, if any


def entry_key(entry: bytes) -> RegionKey:
    return (struct.unpack_from("<H", entry, TRACK_OBJECT_AT)[0],
            struct.unpack_from("<I", entry, ENTRY_TICK_AT)[0] - REGION_BAR_ONE + BAR_ONE,
            struct.unpack_from("<H", entry, 0)[0])


def region_label(key: RegionKey) -> str:
    return f"object {key[0]} at tick {key[1]} (type 0x{key[2]:02x})"


def placed(records) -> list[Placed]:
    """The song container's entries, in order, with what each one carries."""
    events = song_events(records)
    if events is None:
        return []
    names = {slot_of(r.raw): file_name(r.raw[HEADER:]) for r in records if r.tag == FILE_TAG}
    out = []
    for off, blocks in entry_blocks(events):
        entry = events[off:off + ENTRY]
        key = entry_key(entry)
        slot = struct.unpack_from("<I", events, off + ENTRY_SLOT_AT)[0]
        counter = file = None
        if key[2] == AUDIO_ENTRY:
            counter = entry_pair(entry)[0]
            file = names.get(counter)
        out.append(Placed(key, blocks, None if slot == NO_SLOT else slot, counter, file))
    return out


def region_keys(records) -> list[RegionKey]:
    """The song container's entries as the keys a writer declares a deletion by."""
    return [p.key for p in placed(records)]


def dangling_files(records) -> dict[str, list]:
    """``entries``: audio entries (any sequence) whose (slot, piece) has no region record;
    ``records``: region records no audio entry names; ``unfiled``: region records whose slot has
    no file record; ``files``: file records whose slot no region record carries; ``doubled``:
    slots two file records carry; ``rba``: slots of RBA Sequence triples no entry names."""
    pairs = set(audio_entry_pairs(records))
    region_pairs = [region_key(r.raw) for r in records if r.tag == REGION_TAG]
    slots = {s for s, _p in region_pairs}
    file_slots = Counter(slot_of(r.raw) for r in records if r.tag == FILE_TAG)
    events = song_events(records) or b""
    named = {struct.unpack_from("<I", events, off + ENTRY_SLOT_AT)[0] for off, _blocks in entry_blocks(events)}
    return {"entries": sorted(pairs - set(region_pairs)), "records": sorted(set(region_pairs) - pairs),
            "unfiled": sorted(k for k in region_pairs if k[0] not in file_slots),
            "files": sorted(set(file_slots) - slots), "doubled": sorted(s for s, n in file_slots.items() if n > 1),
            "rba": sorted(set(rba_sequences(records)) - named)}


def unregistered_slots(records) -> list[str]:
    """Entries whose `+32` slot names no sequence triple, or one without its pair in both
    registry slot runs (`registry.register_slot`); with no registry, every slotted entry."""
    events = song_events(records)
    if events is None:
        return []
    g = next((r.raw[HEADER:] for r in records if r.tag == GNOS_TAG), None)
    runs = [set(), set()] if g is None else [{s for _at, s in run_entries(g, SLOT_TYPE, stride)}
                                             for stride in (UUID_STRIDE, TIME_STRIDE)]
    slots = {t.slot for t in sequences(records)}
    out = []
    for off, _blocks in entry_blocks(events):
        slot = struct.unpack_from("<I", events, off + ENTRY_SLOT_AT)[0]
        if slot == NO_SLOT:
            continue
        where = region_label(entry_key(events[off:off + ENTRY]))
        if slot not in slots:
            out.append(f"{where}: slot {slot} names no sequence")
        elif any(slot not in run for run in runs):
            out.append(f"{where}: slot {slot} has no registry entry")
    return out


def marker_block_errors(records) -> list[str]:
    """A straight 80-byte walk of the song container against `entry_offsets`: the body a whole
    number of chunks, no block before the first entry, every chunk marked `0xAA` at byte 7
    exactly when it carries the block's `0x88` bytes — else a block reads as an entry — and
    each list's hit targets strictly rising, as on every Logic save under `resources/`."""
    events = song_events(records)
    if events is None:
        return []
    body, out = len(events) - TAIL, []
    if body < 0 or body % ENTRY:
        out.append(f"the events are {len(events)} bytes: not whole {ENTRY}-byte chunks and a {TAIL}-byte tail")
    owner, k, last = "before the first entry", 0, None
    for off in range(0, max(body, 0) - max(body, 0) % ENTRY, ENTRY):
        chunk = events[off:off + ENTRY]
        marked = chunk[MARKER_KIND_AT] == MARKER_KIND
        signed = all(chunk[at] == MARKER_BYTE for at in MARKER_BYTES_AT)
        if not marked and not signed:
            owner, k, last = region_label(entry_key(chunk)), 0, None
            continue
        k += 1
        if owner == "before the first entry":
            out.append(f"marker block {k} {owner}")
        elif marked != signed:
            out.append(f"{owner}, marker block {k}: " + ("marked without its 0x88 bytes" if marked else
                                                         "0x88 bytes without the 0xAA mark — read as an entry"))
        elif chunk[KIND_AT] in (HIT, OFF):
            _source, _kind, whole, fraction = block_fields(chunk)
            target = whole + fraction / 0x10000
            if last is not None and target <= last:
                out.append(f"{owner}, marker block {k}: target at or before the previous hit's")
            last = target
    return out


def _grouped(entries: Iterable[Placed], by: Callable, value: Callable = attrgetter("key")) -> dict:
    out: dict = defaultdict(list)
    for p in entries:
        if by(p) is not None:
            out[by(p)].append(value(p))
    return out


def _moved(was: list[Placed], now: list[Placed], excused: Counter) -> list[str]:
    out = []
    for name in ("slot", "counter"):
        before, after = _grouped(was, attrgetter(name)), _grouped(now, attrgetter(name))
        for ident, keys in before.items():
            gone = Counter(keys) - Counter(after.get(ident, ())) - excused
            if ident in after and gone:
                out += [f"{name} {ident}: {region_label(key)} -> " + ", ".join(map(region_label, sorted(after[ident])))
                        for key in sorted(gone.elements())]
    return sorted(out)


def _audio_place(p: Placed) -> tuple[int, int] | None:
    return p.key[:2] if p.key[2] == AUDIO_ENTRY else None


def _refiled(was: list[Placed], now: list[Placed], removed: Counter) -> list[str]:
    before, after = _grouped(was, _audio_place, attrgetter("file")), _grouped(now, _audio_place, attrgetter("file"))
    show = lambda names: ", ".join(sorted(n or "no file" for n in names))  # noqa: E731
    return sorted(f"{region_label((*at, AUDIO_ENTRY))}: {show(names)} -> {show(after[at])}"
                  for at, names in before.items()
                  if at in after and (*at, AUDIO_ENTRY) not in removed and Counter(names) - Counter(after[at]))


def _reblocked(was: list[Placed], now: list[Placed], excused: Counter) -> tuple[list[str], list[str]]:
    blocks = attrgetter("blocks")
    before, after = _grouped(was, attrgetter("key"), blocks), _grouped(now, attrgetter("key"), blocks)
    lost, gained = [], []
    for key, counts in after.items():
        if key in excused:
            continue
        had = before.get(key, [])
        change = f"{region_label(key)}: {sum(had)} -> {sum(counts)}"
        if had and sum(map(bool, counts)) < sum(map(bool, had)):
            lost.append(change)
        if key[2] == MIDI_ENTRY and sum(counts) > sum(had):
            gained.append(change)
    return sorted(lost), sorted(gained)


def region_regressions(was: dict, now: dict, removed: Iterable[RegionKey]) -> list[str]:
    """What the write lost of the input's regions: `integrity.regressions` for the song container."""
    out, removed = [], Counter(removed)
    lost = Counter(p.key for p in was["regions"]) - Counter(p.key for p in now["regions"]) - removed
    if lost:
        out.append(f"lost_regions: {lost.total()} region(s) the input placed are gone from the song "
                   f"container: {[region_label(k) for k in sorted(lost.elements())]}")
    for part, label in (("entries", "audio entries with no region record"),
                        ("records", "region records no entry names"),
                        ("unfiled", "region records with no file record"),
                        ("files", "file records no region record names"),
                        ("doubled", "file slots carried by two records"),
                        ("rba", "RBA Sequence triples no entry names")):
        before, after = was["dangling_files"].get(part, []), now["dangling_files"][part]
        if len(after) > len(before):
            out.append(f"dangling_files: {label} {len(before)} -> {len(after)}: {sorted(set(after) - set(before))}")
    excused = removed + lost
    lost_blocks, gained_blocks = _reblocked(was["regions"], now["regions"], excused)
    for findings, label in ((_refiled(was["regions"], now["regions"], removed),
                             "dangling_files: {} audio placement(s) now play another file"),
                            (_moved(was["regions"], now["regions"], excused),
                             "moved_regions: {} region(s) whose sequence slot or audio counter now sits elsewhere"),
                            (lost_blocks, "marker_blocks: {} flexed entr(ies) lost their marker blocks"),
                            (gained_blocks, "marker_blocks: {} MIDI entr(ies) gained marker blocks")):
        if findings:
            out.append(f"{label.format(len(findings))}: {findings}")
    for field, label in (("unregistered_slots", "region entr(ies) whose slot has no sequence or no "
                          "registry pair"),
                         ("marker_blocks", "flex marker block(s) cut short, before any entry, missing a "
                          "mark, or with a hit target not after the one before")):
        fresh = sorted(set(now[field]) - set(was[field]))
        if fresh:
            out.append(f"{field}: {len(fresh)} {label}: {fresh}")
    return out
