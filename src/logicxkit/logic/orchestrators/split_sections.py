"""`split-sections`: what the named tracks play during the sections of one name, cut out at those
sections' edges and, given a destination, moved onto another track.

`plan_split` reads the arrangement's sections of that name and each audio region on the named
tracks: the section edges inside a region cut it into spans alternately outside and inside those
sections, and a span shorter than ``min_piece_s`` merges into the span before it (the first into
the one after), so a hand cut a beat off a section's edge is not cut again. `apply_split` makes
the cuts with `split_region`, naming each piece ``<stem>.N`` (`AudioRegion.stem`,
`name_numbers`), and puts the inside spans on the destination with `move_to_track`; pieces are re-found
between edits by their record's (slot, piece), and one listing per region checks every piece
landed where the plan put it.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..services.arrange.stacks import read_tracks
from ..services.arrange.trackname import one_object
from ..services.regions.audio_regions import AUDIO_ENTRY, AudioRegion, highest_pieces, name_numbers
from ..services.regions.fades import Fade
from ..services.regions.overlap import require_no_crossfade
from ..services.regions.region_edit import audio_track, move_to_track, rename_region, set_fade, split_region
from ..services.regions.region_locate import Located, listed, renumbered, samples_per_tick_of
from ..services.song.arrangement import Section, read_sections
from ..services.song.events import BAR_ONE
from ..services.stream.stream import project_records
from ..services.stream.validate import require_valid


@dataclass(frozen=True)
class Span:
    start: int                 # ticks
    end: int
    inside: bool               # within a section of the name
    slivers: tuple[tuple[int, int, bool], ...] = ()   # the shorter spans merged into this one

    @property
    def ticks(self) -> int:
        return self.end - self.start


@dataclass(frozen=True)
class RegionPlan:
    region: AudioRegion
    ident: tuple
    spans: list[Span]
    to: str | None
    spt: float
    rate: int

    @property
    def key(self) -> tuple[int, int, int]:
        return (self.region.object_id, self.region.start, AUDIO_ENTRY)

    @property
    def cuts(self) -> list[int]:
        return [s.start for s in self.spans[1:]]

    @property
    def moves(self) -> list[Span]:
        return [s for s in self.spans if s.inside] if self.to else []

    @property
    def unchanged(self) -> bool:
        return not self.cuts and not self.moves

    @property
    def head_moves(self) -> bool:
        """Whether the region's own entry leaves its track, so its key is one the gate excuses."""
        return bool(self.to) and self.spans[0].inside

    def seconds(self, tick: int) -> float:
        """Seconds from bar 1."""
        return (tick - BAR_ONE) * self.spt / self.rate


def _end(r: AudioRegion, spt: float) -> int:
    return r.start + round(r.frames / spt)


def _joined(spans: list[Span]) -> list[Span]:
    """Neighbouring spans on the same side of the sections as one (two sections of the name abut)."""
    out: list[Span] = []
    for s in spans:
        if out and out[-1].inside == s.inside:
            out[-1] = Span(out[-1].start, s.end, s.inside, (*out[-1].slivers, *s.slivers))
        else:
            out.append(s)
    return out


def _spans(start: int, end: int, sections: list[Section], min_ticks: float) -> list[Span]:
    edges = sorted({t for s in sections for t in (s.start, s.start + s.length) if start < t < end})
    points = [start, *edges, end]
    spans = _joined([Span(p, q, any(s.start <= p < s.start + s.length for s in sections))
                     for p, q in zip(points, points[1:], strict=False)])
    while len(spans) > 1 and any(s.ticks < min_ticks for s in spans):
        k = next(i for i, s in enumerate(spans) if s.ticks < min_ticks)
        host, sliver = (spans[k - 1], spans[k]) if k else (spans[1], spans[0])
        merged = Span(min(host.start, sliver.start), max(host.end, sliver.end), host.inside,
                      (*host.slivers, (sliver.start, sliver.end, sliver.inside), *sliver.slivers))
        spans = _joined([*spans[:k - 1], merged, *spans[k + 1:]] if k else [merged, *spans[2:]])
    return spans


def _require_room(plans: list[RegionPlan], regions: list[Located], spt: float) -> None:
    """A piece landing over a region already on its destination, or over another piece this run
    moves there, is refused by name."""
    moves = [(plan, span) for plan in plans for span in plan.moves]
    for i, (plan, span) in enumerate(moves):
        for loc in regions:
            o = loc.audio
            if o.track == plan.to and o.start < span.end and _end(o, spt) > span.start:
                raise ValueError(f"{plan.region.track}'s {plan.region.name!r} from {plan.seconds(span.start):.1f} s "
                                 f"would land over {o.name!r} on {plan.to!r}")
        for other, span2 in moves[:i]:
            if other.to == plan.to and span2.start < span.end and span.start < span2.end:
                raise ValueError(f"{plan.region.track}'s {plan.region.name!r} from {plan.seconds(span.start):.1f} s and "
                                 f"{other.region.track}'s {other.region.name!r} from {other.seconds(span2.start):.1f} s "
                                 f"would land over each other on {plan.to!r}")


def plan_split(data: bytes, tracks: list[str], section: str, to: dict[str, str], *, rate: int | None,
               min_piece_s: float, track_count: int | None) -> list[RegionPlan]:
    rows = read_tracks(data, track_count)
    for track in tracks:
        if to.get(track) is not None and audio_track(rows, to[track]) == one_object(rows, track):
            raise ValueError(f"{to[track]!r} is the track itself; --to names another track")
        one_object(rows, track)
    sections = [s for s in read_sections(data) if s.name == section]
    if not sections:
        raise ValueError(f"no section named {section!r}")
    if not rate:
        raise ValueError("the project's sample rate is unknown; an audio region's length in ticks needs it")
    spt = samples_per_tick_of(data, rate)
    min_ticks = min_piece_s * rate / spt
    regions = [loc for loc in listed(data, track_count) if loc.audio]
    plans = [RegionPlan(loc.audio, loc.ident, _spans(loc.audio.start, _end(loc.audio, spt), sections, min_ticks),
                        to.get(loc.audio.track), spt, rate)
             for loc in regions if loc.audio.track in tracks]
    require_no_crossfade([p.region for p in plans if not p.unchanged], [loc.audio for loc in regions], spt)
    _require_room(plans, regions, spt)
    return plans


def apply_split(data: bytes, plans: list[RegionPlan], *, track_count: int | None) -> tuple[bytes, dict]:
    """``data`` with every plan's cuts made and its pieces moved; ``{"regions", "pieces", "moved"}``
    counts what changed. Every edit skips its own validation; the file is validated once at the end."""
    records = project_records(data)
    highest, named = highest_pieces(records), name_numbers(records)
    made = {"regions": 0, "pieces": 0, "moved": 0}
    for plan in plans:
        if plan.unchanged:
            continue
        data, pieces, moved = _cut(data, plan, highest, named, track_count=track_count)
        made["regions"] += 1
        made["pieces"] += pieces
        made["moved"] += moved
    require_valid(data)
    return data, made


def _cut(data: bytes, plan: RegionPlan, highest: dict[int, int], named: dict[int, int], *,
         track_count: int | None) -> tuple[bytes, int, int]:
    r, slot, stem = plan.region, plan.region.file_slot, plan.region.stem
    pieces: list[tuple[tuple, Span]] = []
    ident = plan.ident
    for k, span in enumerate(plan.spans):
        pieces.append((ident, span))
        if k == len(plan.spans) - 1:
            break
        data = split_region(data, renumbered(data, ident, track_count), plan.spans[k + 1].start, spt=plan.spt,
                            track_count=track_count, validate=False)
        highest[slot] += 1
        ident = ("audio", (slot, highest[slot]))
        named[slot] += 1
        data = rename_region(data, renumbered(data, ident, track_count), f"{stem}.{named[slot]}", track_count, validate=False)
    for k, (ident, span) in enumerate(pieces):
        fade = Fade.for_piece(r.fade, first=k == 0, last=k == len(pieces) - 1).fitted(round(span.ticks * plan.spt * 1000 / plan.rate))
        data = set_fade(data, renumbered(data, ident, track_count), fade, track_count, validate=False)
    moved = 0
    for ident, span in pieces:
        if plan.to and span.inside:
            data = move_to_track(data, renumbered(data, ident, track_count), plan.to, track_count, validate=False)
            moved += 1
    found = {loc.ident: loc for loc in listed(data, track_count) if loc.audio}
    frames = 0
    for ident, span in pieces:
        loc = found.get(ident)
        track = plan.to if plan.to and span.inside else r.track
        if loc is None or (loc.audio.track, loc.audio.start) != (track, span.start):
            raise ValueError(f"the cuts on {r.track}'s region {r.name!r} did not land where planned")
        frames += loc.audio.frames
    if frames != r.frames:
        raise ValueError(f"the pieces of {r.track}'s region {r.name!r} do not add up to it")
    return data, len(pieces), moved
