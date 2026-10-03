"""`quantize-drums --bars`: the hits of a region's marker list that fall inside a bar range
move onto the grid; every other block keeps its bytes (the logic README, "Flex and audio
quantize").

A hit's place is its source in ticks from the region start, or its target when the source lies
outside the region. Only kind 01 blocks are written: a kept kind 05 block becomes 01 with its
target unchanged, since a list mixing the two kinds is unmeasured. In-range hits sharing a grid
target keep the nearest, as Logic does on load; one landing on a kept hit's target gives way.
A hit whose grid target would cross a kept hit's is refused, as is a region whose grid from its
own start is not the song's grid by the meter: the full quantize snaps region-relative.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field

from .audio_regions import AudioRegion
from ..song.events import BAR_ONE, PPQ
from .flexmarkers import (
    HIT, KIND_AT, MARKER, OFF, START, anchors, block_fields, grid_of, marker_block, samples_per_tick, ticks_of,
)
from ..song.signature import Meter

HIT_KINDS = (HIT, OFF)


@dataclass
class RangePlan:
    blocks: list[bytes] = field(default_factory=list)
    moved: int = 0              # in-range hits written on the grid
    kept: int = 0               # hits outside the range, bytes kept (a kind 05 turned 01)
    merged: int = 0             # in-range hits dropped for a shared target


def bar_span(meter: Meter, first: int, last: int) -> tuple[int, int]:
    """``[start, end)`` in song ticks of bars ``first`` to ``last``, both included."""
    if first < 1 or last < first:
        raise ValueError(f"bars {first}-{last}: the first bar is 1 or later and not past the last")
    return meter.tick(first), meter.tick(last + 1)


def chunks(blocks: bytes) -> list[bytes]:
    return [blocks[i:i + MARKER] for i in range(0, len(blocks) - len(blocks) % MARKER, MARKER)]


def has_hits(blocks: list[bytes]) -> bool:
    return any(b[KIND_AT] in HIT_KINDS for b in blocks)


def overlaps(start: int, frames: int, spt: float, span: tuple[int, int]) -> bool:
    return start < span[1] and start + frames / spt > span[0]


def unmoved(hits: list[int], spt: float) -> list[bytes]:
    """Kind 01 blocks whose targets are the hits' own places: the audio as recorded."""
    out = []
    for h in sorted(hits):
        whole, fraction = ticks_of(h, spt)
        out.append(marker_block(h, whole, HIT, fraction))
    return out


def hit_run(blocks: list[bytes]) -> tuple[list[bytes], list[bytes], list[bytes]]:
    """(blocks before the first hit, first hit to last, the rest); with no hit, the start
    anchors lead and everything else follows."""
    at = [k for k, b in enumerate(blocks) if b[KIND_AT] in HIT_KINDS]
    if not at:
        lead = next((k for k, b in enumerate(blocks) if b[KIND_AT] != START), len(blocks))
        return blocks[:lead], [], blocks[lead:]
    return blocks[:at[0]], blocks[at[0]:at[-1] + 1], blocks[at[-1] + 1:]


def _target(block: bytes) -> float:
    _source, _kind, whole, fraction = block_fields(block)
    return whole + fraction / 0x10000


def _place(block: bytes, frames: int, spt: float) -> float:
    source = block_fields(block)[0]
    return source / spt if 0 <= source < frames else _target(block)


def _as_hit(block: bytes) -> bytes:
    b = bytearray(block)
    b[KIND_AT] = HIT
    return bytes(b)


def _bar(meter: Meter, tick: float) -> int:
    return math.floor(meter.bar(round(tick)))


def grid_mismatch(meter: Meter, start: int, grid: int, end: int) -> str | None:
    """Why the 1/``grid`` grid counted from ``start`` is not the song's up to ``end``, or None."""
    step = PPQ * 4 // grid
    bar = _bar(meter, start)
    if (start - meter.tick(bar)) % step:
        return f"starts {start - meter.tick(bar)} ticks into bar {bar}, off the 1/{grid} grid"
    while meter.tick(bar) < end:
        length = meter.tick(bar + 1) - meter.tick(bar)
        if length % step:
            return f"bar {bar} ({length} ticks) is not whole 1/{grid} notes"
        bar += 1
    return None


def _refuse_crossing(hits: list[bytes], fresh: range, places: list[float], *, start: int, frames: int, spt: float,
                     grid: int, meter: Meter) -> None:
    for i in fresh:
        for j in (i - 1, i + 1):
            if not 0 <= j < len(hits) or j in fresh:
                continue
            low, high = sorted((i, j))
            if _target(hits[high]) <= _target(hits[low]):
                kept = _bar(meter, start + _place(hits[j], frames, spt))
                raise ValueError(f"bar {_bar(meter, start + places[i - fresh.start])}: a hit moved onto the 1/{grid} "
                                 f"grid would cross the target of a kept hit in bar {kept}, putting the markers out of "
                                 f"order; take bar {kept} into --bars")


def requantize(blocks: list[bytes], *, start: int, frames: int, spt: float, grid: int,
               span: tuple[int, int], meter: Meter) -> RangePlan:
    """``blocks``: the region's marker list; ``start``: the region's song tick. The blocks
    before the first hit and after the last stay where they are."""
    head, run, tail = hit_run(blocks)
    if not run:
        return RangePlan(list(blocks))
    stray = [b[KIND_AT] for b in run if b[KIND_AT] not in HIT_KINDS]
    if stray:
        raise ValueError(f"a kind {stray[0]:02x} marker block sits between hits; re-quantizing such a list is unmeasured")
    step = PPQ * 4 // grid
    nearest: dict[int, tuple[float, int, float]] = {}
    order: list[bytes | None] = []
    inside, k = 0, None
    for b in run:
        place = _place(b, frames, spt)
        if not span[0] <= start + place < span[1]:
            order.append(b if b[KIND_AT] == HIT else _as_hit(b))
            continue
        inside += 1
        target = round(place / step) * step
        if target not in nearest or abs(place - target) < nearest[target][0]:
            nearest[target] = (abs(place - target), block_fields(b)[0], place)
        if k is None:
            k = len(order)
            order.append(None)
    if k is None:
        return RangePlan([*head, *order, *tail], kept=len(order))
    held = {block_fields(b)[2:] for b in order if b is not None}
    moves = [(target, source, place) for target, (_d, source, place) in sorted(nearest.items()) if (target, 0) not in held]
    fresh = [marker_block(source, target, HIT) for target, source, _place in moves]
    hits = [*order[:k], *fresh, *order[k + 1:]]
    _refuse_crossing(hits, range(k, k + len(fresh)), [place for _t, _s, place in moves],
                     start=start, frames=frames, spt=spt, grid=grid, meter=meter)
    return RangePlan([*head, *hits, *tail], moved=len(fresh), kept=len(order) - 1, merged=inside - len(fresh))


def own_hits(region: AudioRegion, hits: list[int], spt: float) -> list[int]:
    """Song-sample hits (bar 1 at 0) in samples from ``region``'s start, those inside it."""
    first = round((region.start - BAR_ONE) * spt)
    return [h - first for h in hits if 0 <= h - first < region.frames]


def region_range(region: AudioRegion, blocks: list[bytes], *, had_code: int | None,
                 detect: Callable[[], tuple[list[int], int]], bpm: float, grid: int | None,
                 span: tuple[int, int], meter: Meter, borrowed: list[bytes] | None = None) -> tuple[RangePlan, int, float] | None:
    """(plan, grid, samples per tick) for one region, None when it lies outside ``span``.
    ``had_code``: its RBA Quantize value, None when never quantized; ``borrowed``: another
    region's hit blocks to take when this one lists none — Logic's first quantize writes the
    hits on the first Q-Reference region alone; ``detect``: the song's hits and their rate, read
    only for a region with no hit blocks to take or no file rate. A region quantized before
    keeps its anchors; a first quantize writes fresh ones."""
    listed = has_hits(blocks)
    rate = region.file.rate if (listed or borrowed) and region.file and region.file.rate else detect()[1]
    spt = samples_per_tick(rate * 60 / bpm)
    if not overlaps(region.start, region.frames, spt, span):
        return None
    label = f"{region.track}'s region {region.name!r}"
    grid = grid or (grid_of(had_code) if had_code is not None else None)
    if not grid:
        raise ValueError(f"{label} " + (
            "was never quantized" if had_code is None else f"holds Quantize value {had_code}, not a grid quantize-drums writes")
            + ": name the grid with --grid")
    why = grid_mismatch(meter, region.start, grid, span[1])
    if why:
        raise ValueError(f"{label} {why}: --bars snaps from the region's start, so it takes only a region "
                         "whose grid is the song's; quantize the whole region without --bars")
    head, run, tail = hit_run(blocks)
    if not listed:
        run = [b if b[KIND_AT] == HIT else _as_hit(b) for b in borrowed] if borrowed else unmoved(own_hits(region, detect()[0], spt), spt)
    if had_code is None or not blocks:
        head, tail = ([a] for a in anchors(frames=region.frames, samples_per_beat=rate * 60 / bpm))
    try:
        plan = requantize([*head, *run, *tail], start=region.start, frames=region.frames, spt=spt, grid=grid,
                          span=span, meter=meter)
    except ValueError as e:
        raise ValueError(f"{label}: {e}") from None
    return plan, grid, spt
