"""Quantize a multitrack drum take on a copy, without Logic — the procedure Logic's own
Quantize-Locked group does by hand (the logic README, "Flex and audio quantize").

The groups that would fight the drum group are switched off; a group named ``group`` that
every member is already in is reused, else made with Editing (Selection) and Quantize-Locked
(Audio); Q-Reference stays on the reference tracks only; every member's flex mode is
Slicing. The reference tracks' audio gives the hits (`onsets.py`), taken region-relative;
each member region gets the same markers — the two anchors and one block per hit with its
target on the 1/``grid`` grid — a flexed, quantized entry and an RBA Sequence triple with the
Quantize value (`flexmarkers.py`), the triple's slot registered like a MIDI region's; an entry
whose slot already names an RBA Sequence keeps that triple. With
``bars``, only the hits inside those bars move (`quantize_range.py`). A tempo track that changes tempo, or reference audio with no hits, is refused before any edit.
"""

from __future__ import annotations

import struct
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from functools import cache, partial
from pathlib import Path

from .audio_regions import AudioRegion, read_audio_regions
from ..arrange.environment import object_id_of
from ..song.events import BAR_ONE
from .flexmarkers import (
    ENTRY_SLOT_AT, GRIDS, MARKER, RBA_CODE_AT, anchors, flexed_entry, hit_blocks, quantize_code, rba_sequences,
    rba_triple, samples_per_tick, ticks_of,
)
from .flexmode import set_flex_mode, set_q_reference
from ..arrange.groups import create_group, read_groups, set_group
from ..stream.stream import HEADER, project_records, reassemble
from ..stream.integrity_regions import NO_SLOT
from ..midi.midi import REGION_BAR_ONE
from .onsets import Detector, merge_hits, onsets, read_wav
from .quantize_range import bar_span, chunks, has_hits, hit_run, own_hits, region_range
from ..stream.recbuild import rec
from .regions import ENTRY, TAIL, TRACK_OBJECT_AT, TRACK_ROW_AT, entry_blocks, entry_offsets, song_container
from ..stream.registry import GNOS_TAG, register_slot
from ..stream.sequence import SLOT_STEP, TABLE_FIRST_SLOT, index_table, sequences, table_entries
from ..song.signature import meter
from ..arrange.stacks import read_tracks
from ..song.tempo import project_tempo, read_tempo_events
from ..arrange.tracklist import arrange_run
from ..arrange.trackname import one_object
from ..stream.validate import require_full_walk, require_valid

GROUP_SETTINGS = ("Volume", "Mute", "Automation Mode", "Editing (Selection)", "Quantize-Locked (Audio)")
LOCK_SETTINGS = ("Editing (Selection)", "Quantize-Locked (Audio)")
ENTRY_TICK_AT = 4
_MAX_ID = 512

WavFinder = Callable[[AudioRegion], Path | None]


@dataclass
class Report:
    members: list[str]
    references: list[str]
    grid: int | None
    bars: tuple[int, int] | None = None
    group: int = 0
    group_created: bool = False
    groups_off: list[str] = field(default_factory=list)
    hits: int = 0
    sources: list[tuple[str, str]] = field(default_factory=list)      # (track, audio file)
    regions: list[tuple[str, int]] = field(default_factory=list)      # (track, marker blocks)
    ranged: list[tuple[str, int, int, int, int]] = field(default_factory=list)  # (track, grid, moved, kept, merged)
    outside: list[str] = field(default_factory=list)                 # tracks whose region misses the bars
    borrowed: list[tuple[str, str, int]] = field(default_factory=list)  # (track, lender, hits) — lists of anchors only

    def lines(self) -> list[str]:
        out = [f"group {self.group} {'made' if self.group_created else 'reused'}; off: {', '.join(self.groups_off) or 'none'}"]
        found = (f"{self.hits} hit(s) from {', '.join(f'{t} ({f})' for t, f in self.sources)}" if self.sources
                 else "the regions' own marker lists")
        if self.bars is None:
            return [*out, f"{found} on the 1/{self.grid} grid", *(f"{track}: {n} marker(s)" for track, n in self.regions)]
        out.append(f"bars {self.bars[0]}-{self.bars[1]}; {found}")
        out += [f"{track}: {n} hit(s) taken from {lender}'s list (its own held only anchors)" for track, lender, n in self.borrowed]
        out += [f"{track}: {moved} hit(s) in bars {self.bars[0]}-{self.bars[1]} on the 1/{grid} grid, {kept} kept, "
                f"{merged} merged; {n} marker(s)"
                for (track, grid, moved, kept, merged), (_t, n) in zip(self.ranged, self.regions, strict=True)]
        if self.outside:
            out.append(f"outside the bars, untouched: {', '.join(self.outside)}")
        return out


def _check_grid(grid: int | None) -> None:
    if grid is not None and grid not in GRIDS:
        raise ValueError(f"grid {grid}: quantize-drums writes {', '.join(map(str, GRIDS[:-1]))} or {GRIDS[-1]} "
                         "(1/N notes; the other values are unmeasured)"
                         + ("; 0 is Quantize Off, whose kind 05 lists it does not write" if grid == 0 else ""))


def _one_tempo(data: bytes) -> float:
    """The song's only tempo; how Logic lays markers across a tempo change is unmeasured."""
    bpms = {e.bpm for e in read_tempo_events(data)}
    if len(bpms) > 1:
        raise ValueError(f"the tempo track changes tempo ({min(bpms):g} to {max(bpms):g} bpm); "
                         "quantize-drums reads one tempo and refuses tempo changes and ramps")
    return bpms.pop() if bpms else project_tempo(data)[1]


def _object_ids(data: bytes, names: Sequence[str], track_count: int | None) -> list[int]:
    rows = read_tracks(data, track_count)
    return [one_object(rows, name) for name in names]


def _groups(data: bytes, member_ids: list[int], regioned: list[int], group: str, groups_off: Sequence[str],
            report: Report) -> bytes:
    """The drum group: one named ``group`` holding every member that has audio regions is reused
    (a member with none needs no quantize), else one is made with every member."""
    for g in read_groups(data):
        if g.name in groups_off and g.on:
            data = set_group(data, g.number, on=False)
            report.groups_off.append(f"{g.number} {g.name}")
    have = next((g for g in read_groups(data) if g.name == group and set(regioned) <= set(g.members)), None)
    if have is None:
        data, made = create_group(data, name=group, members=member_ids, settings=list(GROUP_SETTINGS))
        report.group, report.group_created = made.number, True
        return data
    missing = [s for s in LOCK_SETTINGS if s not in have.settings]
    if missing or not have.on:
        data = set_group(data, have.number, settings=have.settings + missing if missing else None, on=True)
    report.group = have.number
    return data


def _objects(data: bytes, member_ids: list[int], ref_ids: list[int]) -> bytes:
    out = []
    for r in project_records(data):
        raw = r.raw
        oid = object_id_of(r)
        if oid in member_ids:
            raw = set_flex_mode(set_q_reference(raw, oid in ref_ids), "Slicing")
        out.append(raw)
    return reassemble(data, out)


def _hits(regions: list[AudioRegion], ref_ids: list[int], wav_of: WavFinder, detector: Detector,
          report: Report, spt_of_rate) -> tuple[list[int], int]:
    """Hit positions in song samples (bar 1 at 0) from the reference regions, and the rate."""
    lists, rate = [], None
    for region in regions:
        if region.object_id not in ref_ids:
            continue
        wav = wav_of(region)
        if wav is None or not Path(wav).exists():
            raise ValueError(f"no audio file for {region.track}'s region {region.name!r} ({region.file.name if region.file else '?'})")
        samples, file_rate = read_wav(wav)
        if rate not in (None, file_rate):
            raise ValueError("the reference files run at different sample rates")
        rate = file_rate
        start = round((region.start - BAR_ONE) * spt_of_rate(rate))
        lists.append([h + start for h in merge_hits([onsets(samples, rate, detector)], rate, offset=region.offset, length=region.frames)])
        report.sources.append((region.track, Path(wav).name))
    if rate is None:
        raise ValueError("no reference region to take the hits from")
    return merge_hits(lists, rate), rate


def _free(records, n: int) -> tuple[list[int], list[int]]:
    """``n`` free table slots and ``n`` free sequence ids."""
    seqs = sequences(records)
    table = records[index_table(records)].raw[HEADER:]
    used_slots = {slot for _at, _oid, _index, slot in table_entries(table)} | {t.slot for t in seqs}
    used_ids = {t.seq_id for t in seqs}
    slots, ids, slot = [], [], TABLE_FIRST_SLOT
    while len(slots) < n:
        if slot not in used_slots:
            slots.append(slot)
        slot += SLOT_STEP
    for i in range(1, _MAX_ID):
        if i not in used_ids:
            ids.append(i)
            if len(ids) == n:
                break
    return slots, ids


def _aligned(a: AudioRegion, b: AudioRegion) -> bool:
    """Two regions whose marker sources mean the same samples: the same start, first frame and length."""
    return (a.start, a.offset, a.frames) == (b.start, b.offset, b.frames)


def _lender(regions: list[AudioRegion], ref_ids: list[int], entries: dict, payload: bytes) -> tuple[AudioRegion, list[bytes]] | None:
    """The first reference region carrying hit blocks, with them: what a member listing only
    anchors takes as its own (Logic's first quantize writes the hits there alone)."""
    for region in regions:
        at = entries.get((region.object_id, region.start - BAR_ONE + REGION_BAR_ONE))
        if region.object_id in ref_ids and at is not None:
            blocks = chunks(payload[at[0] + ENTRY:at[0] + ENTRY + at[1] * MARKER])
            if has_hits(blocks):
                return region, blocks
    return None


def _with_markers(payload: bytes, plans: dict[int, bytes]) -> bytes:
    """The container with each planned entry (by offset) and its marker blocks replaced by the
    plan's bytes; other entries keep theirs."""
    body, tail = payload[:len(payload) - TAIL], payload[len(payload) - TAIL:]
    offsets = entry_offsets(payload)
    out = bytearray()
    for k, off in enumerate(offsets):
        end = offsets[k + 1] if k + 1 < len(offsets) else len(body)
        out += plans.get(off, body[off:end])
    return bytes(out) + tail


def _detected(regions, ref_ids, wav_of, detector, report, bpm) -> tuple[list[int], int]:
    hits, rate = _hits(regions, ref_ids, wav_of, detector, report, lambda r: samples_per_tick(r * 60 / bpm))
    if not hits:
        raise ValueError(f"no hits found in the reference tracks' audio ({', '.join(f for _t, f in report.sources)})")
    report.hits = len(hits)
    return hits, rate


def quantize_drums(data: bytes, *, members: Sequence[str], references: Sequence[str], wav_of: WavFinder,
                   grid: int | None = None, group: str = "Drums", groups_off: Sequence[str] = ("OH", "Room"),
                   detector: Detector = Detector(), track_count: int | None = None,
                   bars: tuple[int, int] | None = None) -> tuple[bytes, Report]:
    """``members``: the drum tracks (names); ``references``: the ones whose hits set the grid
    moves; ``wav_of`` finds a region's audio file; ``bars``: (first, last) re-quantizes only the
    hits in those bars (`quantize_range.py`), where ``grid`` None keeps each region's own value
    (1/16 without ``bars``). Returns (project, report)."""
    if not references or any(r not in members for r in references):
        raise ValueError("the reference tracks must be among the members")
    _check_grid(grid)
    require_full_walk(data)
    grid = 16 if grid is None and bars is None else grid
    bpm = _one_tempo(data)
    report = Report(list(members), list(references), grid, bars=bars)
    member_ids = _object_ids(data, members, track_count)
    ref_ids = [member_ids[members.index(r)] for r in references]
    regions = [r for r in read_audio_regions(data, track_count) if r.object_id in member_ids]
    if not regions:
        raise ValueError("no audio regions on the member tracks")
    detect = cache(partial(_detected, regions, ref_ids, wav_of, detector, report, bpm))
    song_meter = meter(data)
    span = bar_span(song_meter, *bars) if bars else None
    if span is None:
        detect()                                                # refused before any edit
    data = _groups(data, member_ids, sorted({r.object_id for r in regions}), group, groups_off, report)
    data = _objects(data, member_ids, ref_ids)
    records = project_records(data)
    run = arrange_run(records, track_count)
    song = song_container(records, run)
    payload = records[song.end].raw[HEADER:]
    entries = {(int.from_bytes(payload[off + TRACK_OBJECT_AT:off + TRACK_OBJECT_AT + 2], "little"),
                int.from_bytes(payload[off + ENTRY_TICK_AT:off + ENTRY_TICK_AT + 4], "little")): (off, n)
               for off, n in entry_blocks(payload)}
    seqs = sequences(records)
    rba_by_slot = rba_sequences(records)
    free_slots, free_ids = _free(records, len(regions))
    plans, triples, updates, new_slots = {}, [], {}, []
    lender = _lender(regions, ref_ids, entries, payload) if span is not None else None
    for region in regions:
        at = entries.get((region.object_id, region.start - BAR_ONE + REGION_BAR_ONE))
        if at is None:
            raise ValueError(f"{region.track}'s region {region.name!r} has no arrange entry at its start")
        off, n = at
        entry = payload[off:off + ENTRY]
        row = int.from_bytes(payload[off + TRACK_ROW_AT:off + TRACK_ROW_AT + 2], "little")
        named = int.from_bytes(entry[ENTRY_SLOT_AT:ENTRY_SLOT_AT + 4], "little")
        had = rba_by_slot.get(named)
        if span is not None and had is None and named != NO_SLOT:
            raise ValueError(f"{region.track}'s region {region.name!r} names a sequence that is no RBA Sequence "
                             f"(slot {named}); --bars would replace it, which is unmeasured")
        had_code = struct.unpack_from("<h", records[had.start].raw, HEADER + RBA_CODE_AT)[0] if had else None
        if span is None:
            hits, rate = detect()
            spb = rate * 60 / bpm
            spt = samples_per_tick(spb)
            start, end = anchors(frames=region.frames, samples_per_beat=spb)
            blocks, code = [start, *hit_blocks(own_hits(region, hits, spt), spt=spt, grid=grid), end], quantize_code(grid)
        else:
            blocks, borrowed = chunks(payload[off + ENTRY:off + ENTRY + n * MARKER]), None
            if lender and region is not lender[0] and not has_hits(blocks) and _aligned(region, lender[0]):
                borrowed = hit_run(lender[1])[1]
                report.borrowed.append((region.track, lender[0].track, len(borrowed)))
            planned = region_range(region, blocks, had_code=had_code, detect=detect, bpm=bpm, grid=grid, span=span,
                                   meter=song_meter, borrowed=borrowed)
            if planned is None:
                report.outside.append(region.track)
                continue
            plan, region_grid, spt = planned
            blocks, code = plan.blocks, quantize_code(region_grid)
            report.ranged.append((region.track, region_grid, plan.moved, plan.kept, plan.merged))
        length, fraction = ticks_of(region.frames, spt)
        if had is not None and span is not None:        # re-quantized in a range: entry and triple stay
            plans[off] = entry + b"".join(blocks)
        elif had is not None:                            # quantized before: its triple stays, re-stamped
            plans[off] = flexed_entry(entry, slot=had.slot) + b"".join(blocks)
            updates[had.start] = rba_triple(seq_id=had.seq_id, slot=had.slot, length_ticks=length, fraction=fraction, code=code,
                                            track_object=region.object_id, row=row)[0]
        else:
            slot, seq_id = free_slots.pop(0), free_ids.pop(0)
            new_slots.append(slot)
            triples.append(rba_triple(seq_id=seq_id, slot=slot, length_ticks=length, fraction=fraction, code=code,
                                      track_object=region.object_id, row=row))
            plans[off] = flexed_entry(entry, slot=slot) + b"".join(blocks)
        report.regions.append((region.track, len(blocks)))
    if span is not None and not any(moved + merged for _t, _g, moved, _k, merged in report.ranged):
        raise ValueError(f"bars {bars[0]}-{bars[1]} hold no hit on the member regions")
    anchor = max(t.end for t in seqs if t.slot < 1024 and t.start > song.start)
    out = []
    for i, r in enumerate(records):
        raw = r.raw
        if i == song.end:
            raw = rec(b"qSvE", raw, _with_markers(raw[HEADER:], plans))
        elif r.tag == GNOS_TAG:
            g = raw[HEADER:]
            for slot in new_slots:
                g = register_slot(g, slot=slot)
            raw = rec(GNOS_TAG, raw, g)
        elif i in updates:
            raw = updates[i]
        out.append(raw)
        if i == anchor:
            for triple in triples:
                out += list(triple)
    result = reassemble(data, out)
    require_valid(result)
    return result, report
