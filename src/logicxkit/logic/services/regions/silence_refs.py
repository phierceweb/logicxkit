"""A mic's reference tracks laid beside its file, hop for hop, for the bleed rule in `silence.py`:
each reference region's envelope is read at the hop the song puts beside the mic's, so the two
regions may sit at different offsets in their files."""

from __future__ import annotations

from .audio_regions import AudioRegion
from .silence import Envelope, Reference


def aligned_references(region: AudioRegion, env: Envelope, refs: list[tuple[AudioRegion, Envelope]], *, spt: float,
          threshold_db: float, order: tuple[str, ...]) -> tuple[list[bool], list[Reference]]:
    """Per hop of ``region``'s file: whether any reference plays there, and, per reference track in
    ``order``, its level at the hop the song puts beside ``region``'s (0 outside its regions) and
    whether it plays there — within ``threshold_db`` of its file's loud level. Only the hops the
    region itself plays count, so audio outside it never sets the floor; a reference whose file is
    silent never plays."""
    hops = len(env.peaks)
    lo, hi = region.offset // env.hop, min(hops, -(-(region.offset + region.frames) // env.hop))
    playing = [False] * hops
    tracks: dict[str, Reference] = {name: ([0] * hops, [False] * hops) for name in order}
    for ref, ref_env in refs:
        if not ref_env.loud:
            continue
        level, plays = tracks[ref.track]
        limit = ref_env.loud * 10 ** (threshold_db / 20)
        first, last = ref.offset // ref_env.hop, min(len(ref_env.peaks), (ref.offset + ref.frames) // ref_env.hop)
        delta = round(((ref.offset - region.offset) + (region.start - ref.start) * spt) / env.hop)
        for h in range(max(lo, first - delta), min(hi, last - delta)):
            p = ref_env.peaks[h + delta]
            level[h] = max(level[h], p)
            if p >= limit:
                plays[h] = playing[h] = True
    return playing, list(tracks.values())
