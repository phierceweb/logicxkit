"""Regions that overlap on one track while a crossfade joins them — the underneath region's
fade-out of a crossfade type, the other starting inside it — a cut of either would leave half a
crossfade on a piece that no longer overlaps, so a writer refuses the ones its plan would cut."""

from __future__ import annotations

from .audio_regions import AudioRegion
from .fades import CROSSFADES


def _end(r: AudioRegion, spt: float) -> int:
    return r.start + round(r.frames / spt)


def require_no_crossfade(cut: list[AudioRegion], regions: list[AudioRegion], spt: float) -> None:
    """A region in ``cut`` that carries a crossfade's bit, or overlaps another of ``regions`` on its
    track while either carries a crossfade, is refused: a cut would leave half a crossfade on a piece
    that no longer overlaps."""
    for r in cut:
        for o in regions:
            if o is r or o.track != r.track:
                continue
            if r.fade.out_type in CROSSFADES and r.start < o.start < _end(r, spt):
                raise ValueError(f"{r.track}'s region {r.name!r} is crossfaded into {o.name!r}; cut it by hand")
            if o.fade.out_type in CROSSFADES and o.start < r.start < _end(o, spt):
                raise ValueError(f"{r.track}'s region {r.name!r} is crossfaded from {o.name!r}; cut it by hand")
        if r.crossfaded:
            raise ValueError(f"{r.track}'s region {r.name!r} carries a crossfade; cut it by hand")
