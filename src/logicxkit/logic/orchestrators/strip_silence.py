"""`strip-silence`: the silent stretches cut out of a track's regions, the cut edges faded.

`plan_strip` reads each named track's regions and, through one envelope per audio file
(`silence.py`), the spans each region keeps: a peak envelope against the file's own loud level,
or, with reference tracks, an RMS envelope (band-limited when asked) against the bleed floor read
while the references play and against the bleed the references predict, each reference's hops
aligned to the region's file by song time. `apply_strip` makes the cuts with the measured
region edits: per gap, a split at the end of the kept span before it and a trim of the new
piece's start to the next; the first span's start and the last span's end trimmed when the
region begins or ends in a gap; a fade on every edge this run cut; a region silent throughout
muted, since there is no region delete. The pieces are named ``<stem>.N`` (`AudioRegion.stem`)
from `name_numbers` — a cut of piece ``take.3`` gives ``take.4``, never ``take.3.1``; a parent keeps its
name, so ``take.3`` as a parent gives ``take.3.1`` — and re-found between
edits by their record's (slot, piece). A kept span shorter than a tick cannot be written and is dropped.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from ..services.arrange.stacks import read_tracks
from ..services.regions.audio_regions import AUDIO_ENTRY, PIECE_LIMIT, AudioRegion, highest_pieces, name_numbers
from ..services.regions.fades import Fade
from ..services.regions.fundamental import fundamental
from ..services.regions.overlap import require_no_crossfade
from ..services.regions.region_edit import rename_region, set_fade, set_mute, split_region, trim_region
from ..services.regions.region_locate import listed, renumbered, samples_per_tick_of
from ..services.regions.silence import Envelope, bleed_stretches, keeps, peak_envelope, quiet_stretches, rms_envelope, writable
from ..services.regions.silence_refs import aligned_references
from ..services.song.events import BAR_ONE
from ..services.stream.stream import project_records
from ..services.stream.validate import require_valid

WavOf = Callable[[AudioRegion], Path | None]


@dataclass(frozen=True)
class Settings:
    threshold_db: float = -30.0        # a quiet hop sits more than this under the file's loud level
    edge_db: float = -20.0             # a gap's edges crop outward over hops under this tighter limit
    min_gap_s: float = 2.0
    min_keep_s: float = 0.5            # a shorter sound between two gaps is a blip, silence too
    pad_ms: tuple[int, int] = (500, 500)   # kept before the first sound and after the last
    fade_ms: int = 20
    band: tuple[int, int] | None = None    # Hz; the envelope is then an RMS within it
    refs: tuple[str, ...] = ()             # tracks whose playing sets where the bleed floor is read
    above_db: float = 9.0                  # over the bleed floor and over the predicted bleed, a mic is heard
    gate_db: float | None = None           # the mic is never heard under this over its floor; None: `above_db`
    window_ms: int = 300                   # the running median the bleed rule reads levels on
    against: tuple[int, int] | None = None # a second band of the mic; a sound is kept only if louder in `band` by `tilt_db`
    tilt_db: float = 0.0
    tilt_band: tuple[int, int] | str | None = None   # the band the tilt is read in instead of `band`; "auto": the file's fundamental

    @property
    def rms(self) -> bool:
        return bool(self.band or self.refs)


@dataclass(frozen=True)
class RegionPlan:
    region: AudioRegion
    ident: tuple
    spt: float
    rate: int
    keeps: list[tuple[int, int]]       # file frames
    loud_db: float
    limit_db: float
    edge_db: float | None = None
    floor_db: float | None = None      # the bleed floor, with references
    note: str = ""                     # what the plan found out for this region, for the listing
    above_db: float | None = None      # over the predicted bleed, with references

    @property
    def key(self) -> tuple[int, int, int]:
        return (self.region.object_id, self.region.start, AUDIO_ENTRY)

    @property
    def end(self) -> int:
        return self.region.offset + self.region.frames

    @property
    def silent(self) -> bool:
        return not self.keeps

    @property
    def unchanged(self) -> bool:
        return self.keeps == [(self.region.offset, self.end)]

    @property
    def cuts(self) -> int:
        if not self.keeps:
            return 0
        return len(self.keeps) - 1 + (self.keeps[0][0] > self.region.offset) + (self.keeps[-1][1] < self.end)

    def tick(self, frame: int) -> int:
        return _tick(self.region, frame, self.spt)

    def seconds(self, frame: int) -> float:
        """Seconds from bar 1."""
        return (self.tick(frame) - BAR_ONE) * self.spt / self.rate


def _tick(piece: AudioRegion, frame: int, spt: float) -> int:
    return piece.start + round((frame - piece.offset) / spt)


def _require_record(wav: Path, env: Envelope, region: AudioRegion) -> None:
    record = region.file
    if record is None:
        return
    if record.rate and env.rate != record.rate:
        raise ValueError(f"{wav.name} is at {env.rate} Hz but the file record of {region.track}'s region {region.name!r} "
                         f"says {record.rate} Hz")
    if record.frames and env.frames != record.frames:
        raise ValueError(f"{wav.name} holds {env.frames} frames but the file record of {region.track}'s region "
                         f"{region.name!r} says {record.frames}; it is not the file the project plays")


Cache = dict[tuple[Path, tuple[int, int] | None, bool], Envelope]       # (file, band, RMS rather than peak)
TILT_BAND_SPAN = (0.7, 1.4)        # around the fundamental


def plan_strip(data: bytes, tracks: list[str], wav_of: WavOf, *, rate: int | None, settings: Settings,
               track_count: int | None, cache: Cache | None = None) -> list[RegionPlan]:
    names = {t["name"] for t in read_tracks(data, track_count)}
    for track in (*tracks, *settings.refs):
        if track not in names:
            raise ValueError(f"no track named {track!r}")
    for track in tracks:
        if track in settings.refs:
            raise ValueError(f"{track!r} is named both as a track to cut and as a reference; a mic cannot be its own reference")
    regions = [loc for loc in listed(data, track_count) if loc.audio]
    for track in (*tracks, *settings.refs):
        if not any(loc.audio.track == track for loc in regions):
            raise ValueError(f"{track!r} has no audio regions")
    if not rate:
        raise ValueError("the project's sample rate is unknown; an audio region's length in ticks needs it")
    for band in (settings.band, settings.against, settings.tilt_band if isinstance(settings.tilt_band, tuple) else None):
        if band and band[1] >= rate / 2:
            raise ValueError(f"band {band[0]}:{band[1]} reaches half the sample rate ({rate // 2} Hz)")
    spt = samples_per_tick_of(data, rate)
    pad = (round(settings.pad_ms[0] * rate / 1000), round(settings.pad_ms[1] * rate / 1000))
    envelopes: Cache = {} if cache is None else cache
    notes: dict[Path, tuple[tuple[int, int], float]] = {}

    def envelope(r: AudioRegion, band: tuple[int, int] | None = settings.band) -> Envelope:
        wav = wav_of(r)
        if wav is None or not Path(wav).exists():
            raise ValueError(f"no audio file for {r.track}'s region {r.name!r} ({r.file.name if r.file else '?'}); --audio DIR names the folder that holds it")
        wav = Path(wav)
        key = (wav, band, settings.rms)
        if key not in envelopes:
            envelopes[key] = rms_envelope(wav, band=band) if settings.rms else peak_envelope(wav)
        _require_record(wav, envelopes[key], r)
        if envelopes[key].rate != rate:
            raise ValueError(f"{wav.name} is at {envelopes[key].rate} Hz; the project is at {rate} Hz")
        return envelopes[key]

    refs = [(loc.audio, envelope(loc.audio)) for loc in regions if loc.audio.track in settings.refs]
    plans = []
    for loc in regions:
        r = loc.audio
        if r.track not in tracks:
            continue
        env = envelope(r)
        if refs:
            playing, references = aligned_references(r, env, refs, spt=spt, threshold_db=settings.threshold_db, order=settings.refs)
            if not any(playing):
                plans.append(RegionPlan(r, loc.ident, spt, rate, [(r.offset, r.offset + r.frames)], env.loud_db, env.loud_db,
                                        note="no reference plays beside it, so its bleed floor cannot be read"))
                continue
            against = envelope(r, settings.against).peaks if settings.against else None
            tilt_band, note = settings.tilt_band, ""
            if settings.against and tilt_band == "auto":
                wav = Path(wav_of(r))
                if wav not in notes:
                    hz = fundamental(wav, env)
                    notes[wav] = (round(hz * TILT_BAND_SPAN[0]), round(hz * TILT_BAND_SPAN[1])), hz
                tilt_band, hz = notes[wav]
                note = f"fundamental {hz:.0f} Hz, tilt band {tilt_band[0]}:{tilt_band[1]}"
            tilted = envelope(r, tilt_band).peaks if settings.against and tilt_band else None
            stretches, floor, usual = bleed_stretches(env, playing, above_db=settings.above_db, min_gap_s=settings.min_gap_s,
                                                      min_keep_s=settings.min_keep_s, references=references,
                                                      window_ms=settings.window_ms, against=against, tilt_db=settings.tilt_db,
                                                      tilted=tilted, gate_db=settings.gate_db)
            gate = settings.above_db if settings.gate_db is None else settings.gate_db
            bleed = ", ".join(f"{name} {ratio:+.1f}" for name, ratio in zip(settings.refs, usual, strict=True) if ratio != math.inf)
            kept, short = _kept(r, stretches, pad, spt)
            note = "; ".join(s for s in (note, f"bleed from {bleed} dB" if bleed else "", short) if s)
            plans.append(RegionPlan(r, loc.ident, spt, rate, kept, env.loud_db, floor + gate, None, floor, note, settings.above_db))
        else:
            stretches = quiet_stretches(env, threshold_db=settings.threshold_db, min_gap_s=settings.min_gap_s,
                                        min_keep_s=settings.min_keep_s, edge_db=settings.edge_db)
            kept, short = _kept(r, stretches, pad, spt)
            plans.append(RegionPlan(r, loc.ident, spt, rate, kept, env.loud_db, env.loud_db + settings.threshold_db,
                                    env.loud_db + settings.edge_db, note=short))
    require_no_crossfade([p.region for p in plans if not p.unchanged and not p.silent], [loc.audio for loc in regions], spt)
    return plans


def _kept(region: AudioRegion, stretches: list[tuple[int, int]], pad: tuple[int, int], spt: float) -> tuple[list[tuple[int, int]], str]:
    """The spans the region keeps that a trim or split can write, an edge within half a tick of the
    region's own taken as it, since no trim can move it; one with none is left whole, with a note."""
    spans = keeps(region.offset, region.frames, stretches, pad=pad)
    kept = writable(spans, spt)
    if spans and not kept:
        return [(region.offset, region.offset + region.frames)], "every kept span is shorter than a tick; left as it is"
    end = region.offset + region.frames
    return [(region.offset if a - region.offset <= spt / 2 else a, end if end - b <= spt / 2 else b) for a, b in kept], ""


def require_piece_room(plans: list[RegionPlan], highest: dict[int, int]) -> None:
    """A file's pieces number on from ``highest`` (by file slot) in two bytes: past `PIECE_LIMIT` is refused."""
    more: dict[int, int] = {}
    for plan in plans:
        if not plan.unchanged and not plan.silent:
            more[plan.region.file_slot] = more.get(plan.region.file_slot, 0) + len(plan.keeps) - 1
    for slot, cuts in more.items():
        last = highest.get(slot, 0) + cuts
        if last > PIECE_LIMIT:
            name = next(plan.region.name for plan in plans if plan.region.file_slot == slot)
            raise ValueError(f"{name!r} would take its file's piece numbers to {last}, past {PIECE_LIMIT}, the most an "
                             f"entry's two bytes hold; a longer --min-gap makes fewer pieces")


def piece_room(data: bytes, plans: list[RegionPlan]) -> None:
    """`require_piece_room` against the project's region records, kept or not."""
    require_piece_room(plans, highest_pieces(project_records(data)))


def apply_strip(data: bytes, plans: list[RegionPlan], *, settings: Settings, track_count: int | None) -> tuple[bytes, dict]:
    """``data`` with every plan's cuts made; ``{"regions", "pieces", "muted"}`` counts what changed.

    Each piece is found again by its (slot, piece) before every edit, its placement follows by the
    arithmetic the writers use (a trim moves the start by the frames the ticks round to), every
    edit skips its own validation, and one listing per region checks every piece landed as planned
    before the file is validated once at the end."""
    piece_room(data, plans)
    records = project_records(data)
    highest, named = highest_pieces(records), name_numbers(records)
    made = {"regions": 0, "pieces": 0, "muted": 0}
    for plan in plans:
        if plan.unchanged:
            continue
        made["regions"] += 1
        if plan.silent:
            data = set_mute(data, renumbered(data, plan.ident, track_count), True, track_count)
            made["muted"] += 1
            continue
        data, pieces = _cut(data, plan, highest, named, settings=settings, track_count=track_count)
        made["pieces"] += pieces
    require_valid(data)
    return data, made


def _cut(data: bytes, plan: RegionPlan, highest: dict[int, int], named: dict[int, int], *, settings: Settings,
         track_count: int | None) -> tuple[bytes, int]:
    r, spt, slot = plan.region, plan.spt, plan.region.file_slot
    start, offset, frames, ident = r.start, r.offset, r.frames, plan.ident
    planned: list[tuple[tuple, int, int, int, bool, bool]] = []     # ident, start, offset, frames, cut start, cut end
    for i, (a, b) in enumerate(plan.keeps):
        tick = start + round((a - offset) / spt)
        cut_start = tick > start
        if cut_start:
            data = trim_region(data, renumbered(data, ident, track_count), start=tick, spt=spt, track_count=track_count, validate=False)
            moved = round((tick - start) * spt)
            start, offset, frames = tick, offset + moved, frames - moved
        if i < len(plan.keeps) - 1:
            cut = start + round((b - offset) / spt)
            data = split_region(data, renumbered(data, ident, track_count), cut, spt=spt, track_count=track_count, validate=False)
            kept = round((cut - start) * spt)
            highest[slot] += 1
            planned.append((ident, start, offset, kept, cut_start, True))
            ident = ("audio", (slot, highest[slot]))
            named[slot] += 1
            data = rename_region(data, renumbered(data, ident, track_count), f"{r.stem}.{named[slot]}", track_count, validate=False)
            start, offset, frames = cut, offset + kept, frames - kept
        else:
            length = round((b - offset) / spt)
            cut_end = b < r.offset + r.frames                  # `_kept` gives an edge it leaves as the region's own
            if cut_end:
                data = trim_region(data, renumbered(data, ident, track_count), length=length, spt=spt, track_count=track_count, validate=False)
                frames = round(length * spt)
            planned.append((ident, start, offset, frames, cut_start, cut_end))
    for k, (ident, _s, _o, frames, cut_start, cut_end) in enumerate(planned):
        fade = Fade.for_piece(r.fade, first=k == 0, last=k == len(planned) - 1)
        if cut_start:
            fade = replace(fade, in_ms=settings.fade_ms, in_curve=0, in_type=0)
        if cut_end:
            fade = replace(fade, out_ms=settings.fade_ms, out_curve=0, out_type=Fade().out_type)
        data = set_fade(data, renumbered(data, ident, track_count), fade.fitted(round(frames * 1000 / plan.rate)), track_count, validate=False)
    found = {loc.ident: loc for loc in listed(data, track_count) if loc.audio}
    for ident, s, o, f, _cs, _ce in planned:
        loc = found.get(ident)
        if loc is None or (loc.audio.start, loc.audio.offset, loc.audio.frames) != (s, o, f):
            raise ValueError(f"the cuts on {r.track}'s region {r.name!r} did not land where planned (piece {ident[1][1]})")
    return data, len(planned)
