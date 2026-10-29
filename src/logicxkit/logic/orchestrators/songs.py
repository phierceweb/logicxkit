"""`songs`: a live set's songs as arrangement sections, one per song, found where the named
tracks all stop.

`plan_songs` reads each named track's regions into one run of quiet flags over the song's 10 ms
hops — a hop is quiet where the track's file sits more than ``threshold_db`` under its loud level
(`silence.peak_envelope`), or where no region of the track plays — and hands the hops every track
is quiet on to `stops.find_stops`. The stretches of playing it leaves are the songs, laid under the
setlist in order when the counts agree; `apply_songs` then writes each as a section from the
stretch's first hop for its length. A section already on the arrangement over a song's stretch is
named in the plan and refused, so a second run on a copy cannot write the songs twice.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..services.arrange.stacks import read_tracks
from ..services.regions.audio_regions import AudioRegion
from ..services.regions.region_locate import listed, regions_end, samples_per_tick_of
from ..services.regions.silence import Envelope, peak_envelope
from ..services.regions.stops import Stops, band_quiet, find_stops
from ..services.song.arrangement import Section, read_sections
from ..services.song.arrangement_write import add_section
from ..services.song.events import BAR_ONE
from ..services.song.setlist import Setlist
from ..services.stream.validate import require_valid

WavOf = Callable[[AudioRegion], Path | None]


@dataclass(frozen=True)
class Settings:
    threshold_db: float = -30.0        # a quiet hop sits more than this under the file's loud level
    min_gap_s: float = 0.5
    min_keep_s: float = 0.3            # a sound shorter than this between two gaps is silence too
    merge_s: float = 15.0              # gaps closer than this of playing are one stop
    min_stop_s: float = 10.0           # a stop this long separates songs
    min_song_s: float = 45.0           # playing shorter than this is not a song


@dataclass(frozen=True)
class SongPlan:
    stops: Stops
    setlist: Setlist
    spt: float
    rate: int
    hop: int                           # frames per hop
    end: int = 0                       # tick: the last region on any track ends here
    sections: tuple[Section, ...] = ()  # already on the arrangement

    @property
    def matched(self) -> bool:
        return len(self.stops.songs) == len(self.setlist)

    @property
    def taken(self) -> list[Section]:
        """The sections already there that a song's stretch would land on."""
        spans = [(self.tick(a), self.tick(b)) for a, b in self.stops.songs]
        return [s for s in self.sections if any(s.start < b and a < s.start + s.length for a, b in spans)]

    def seconds(self, hop: int) -> float:
        return hop * self.hop / self.rate

    def tick(self, hop: int) -> int:
        return BAR_ONE + round(hop * self.hop / self.spt)

    def songs(self) -> list[tuple[str, int, int]]:
        """``(name, start tick, length in ticks)`` per song, the setlist laid over the stretches."""
        if not self.matched:
            raise ValueError(f"the setlist names {len(self.setlist)} song(s) and the set holds {len(self.stops.songs)} stretch(es) of playing")
        if self.taken:
            raise ValueError(f"the arrangement already has {len(self.taken)} section(s) where the songs play, "
                             f"{self.taken[0].name!r} first")
        return [(name, self.tick(a), self.tick(b) - self.tick(a))
                for name, (a, b) in zip(self.setlist.songs, self.stops.songs, strict=True)]

    def stop_after(self, song: int) -> tuple[int, int] | None:
        """The stop right after song ``song`` (1-based), when the setlist is laid over."""
        if not self.matched or not 1 <= song <= len(self.stops.songs):
            return None
        end = self.stops.songs[song - 1][1]
        return next((s for s in self.stops.stops if s[0] >= end), None)


def plan_songs(data: bytes, tracks: list[str], wav_of: WavOf, *, rate: int | None, settings: Settings,
               track_count: int | None, setlist: Setlist, cache: dict[Path, Envelope] | None = None) -> SongPlan:
    names = {t["name"] for t in read_tracks(data, track_count)}
    for track in tracks:
        if track not in names:
            raise ValueError(f"no track named {track!r}")
    regions = [loc.audio for loc in listed(data, track_count) if loc.audio and loc.audio.track in tracks]
    for track in tracks:
        if not any(r.track == track for r in regions):
            raise ValueError(f"{track!r} has no audio regions")
    if not rate:
        raise ValueError("the project's sample rate is unknown; a region's place in the song needs it")
    spt = samples_per_tick_of(data, rate)
    envelopes: dict[Path, Envelope] = {} if cache is None else cache

    def envelope(r: AudioRegion) -> Envelope:
        wav = wav_of(r)
        if wav is None or not Path(wav).exists():
            raise ValueError(f"no audio file for {r.track}'s region {r.name!r} ({r.file.name if r.file else '?'}); --audio DIR names the folder that holds it")
        wav = Path(wav)
        if wav not in envelopes:
            envelopes[wav] = peak_envelope(wav)
        if envelopes[wav].rate != rate:
            raise ValueError(f"{wav.name} is at {envelopes[wav].rate} Hz; the project is at {rate} Hz")
        return envelopes[wav]

    hop = envelope(regions[0]).hop
    hops = max(math.ceil(((r.start - BAR_ONE) * spt + r.frames) / hop) for r in regions)
    limit = 10 ** (settings.threshold_db / 20)
    per_track: list[list[bool]] = []
    for track in tracks:
        quiet = [True] * hops
        for r in regions:
            if r.track != track:
                continue
            env = envelope(r)
            loud = env.loud * limit
            base = (r.start - BAR_ONE) * spt - r.offset        # song frame = file frame + base
            first, last = r.offset // hop, min(len(env.peaks), math.ceil((r.offset + r.frames) / hop))
            for k in range(first, last):
                h = round((k * hop + base) / hop)
                if 0 <= h < hops and env.peaks[k] >= loud:
                    quiet[h] = False
        per_track.append(quiet)
    stops = find_stops(band_quiet(per_track, hops), hop_s=hop / rate, min_gap_s=settings.min_gap_s,
                       min_keep_s=settings.min_keep_s, merge_s=settings.merge_s, min_stop_s=settings.min_stop_s,
                       min_song_s=settings.min_song_s)
    end = regions_end(listed(data, track_count), spt)
    last = BAR_ONE + round(stops.songs[-1][1] * hop / spt) if stops.songs else end
    if 0 < end - last < hop / spt:                             # a last part-hop of sound has no hop of its own
        end = last
    return SongPlan(stops, setlist, spt, rate, hop, end, tuple(read_sections(data)))


def apply_songs(data: bytes, plan: SongPlan) -> bytes:
    """``data`` with one section per song; the sections are written in order, so the plan's
    stretches and the setlist's names pair as `SongPlan.songs` lays them."""
    for name, start, length in plan.songs():
        data = add_section(data, name, start=start, length=length)
    require_valid(data)
    return data
