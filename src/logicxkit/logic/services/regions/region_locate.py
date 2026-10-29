"""Which region a listing number names. `listed` walks every audio and MIDI region in the
`regions` listing's order (by row, start, audio before MIDI); a `Located` carries the region, its
kind, and for a MIDI region its place among the entries playing one sequence, so an edit that
must touch one region alone can refuse an alias. Audio lengths are frames; ticks convert through
samples per tick at the song's one tempo."""

from __future__ import annotations

from dataclasses import dataclass

from .audio_regions import AUDIO_ENTRY, AudioRegion, read_audio_regions
from .flexmarkers import samples_per_tick
from ..midi.midi import MIDI_ENTRY, MidiRegion, read_midi
from ..song.tempo import project_tempo, read_tempo_events


@dataclass(frozen=True)
class Located:
    number: int
    kind: str                  # "midi" or "audio"
    midi: MidiRegion | None = None
    audio: AudioRegion | None = None
    alias: int = 0             # a MIDI region's place among the entries playing its sequence
    aliases: int = 1           # how many entries play it

    @property
    def region(self):
        return self.midi if self.kind == "midi" else self.audio

    @property
    def key(self) -> tuple[int, int, int]:
        """The entry's `integrity_regions.RegionKey`."""
        return (self.region.object_id, self.region.start, AUDIO_ENTRY if self.kind == "audio" else MIDI_ENTRY)

    @property
    def ident(self) -> tuple:
        """What stays the same across edits: an audio record's (slot, piece); a MIDI sequence's slot
        and the region's place among the entries playing it (aliases), in container order."""
        return ("audio", self.audio.record_key) if self.audio else ("midi", self.midi.slot, self.alias)


def listed(data: bytes, track_count: int | None = None) -> list[Located]:
    """Every region in the `regions` listing's order: by row, start, audio before MIDI."""
    midi = read_midi(data, track_count)
    by_slot: dict[int, list[int]] = {}
    for r in sorted(midi, key=lambda r: r.at):
        by_slot.setdefault(r.slot, []).append(r.at)
    rows = [(r.row, r.start, "audio", i, r) for i, r in enumerate(read_audio_regions(data, track_count))]
    rows += [(r.row, r.start, "midi", i, r) for i, r in enumerate(midi)]
    rows.sort(key=lambda x: x[:4])
    return [Located(n, kind, r if kind == "midi" else None, r if kind == "audio" else None,
                    by_slot[r.slot].index(r.at) if kind == "midi" else 0, len(by_slot[r.slot]) if kind == "midi" else 1)
            for n, (_row, _start, kind, _i, r) in enumerate(rows, 1)]


def located(data: bytes, number: int, track_count: int | None = None) -> Located:
    regions = listed(data, track_count)
    if not 1 <= number <= len(regions):
        raise ValueError(f"region {number}: the listing has {len(regions)} region(s)")
    return regions[number - 1]


def renumbered(data: bytes, ident: tuple, track_count: int | None = None) -> int:
    """The listing number region ``ident`` (`Located.ident`) has now, after earlier edits."""
    for loc in listed(data, track_count):
        if loc.ident == ident:
            return loc.number
    raise ValueError(f"the region {ident} is no longer in the listing")


def samples_per_tick_of(data: bytes, rate: int) -> float:
    """Frames per tick at the song's one tempo; a song whose tempo changes is refused."""
    bpms = {round(e.bpm, 4) for e in read_tempo_events(data)} | {round(project_tempo(data)[1], 4)}
    if len(bpms) > 1:
        raise ValueError("the tempo changes; an audio region's length in ticks needs one tempo")
    return samples_per_tick(rate * 60 / bpms.pop())


def regions_end(regions: list[Located], spt: float | None) -> int:
    """The tick the last of ``regions`` ends on, 0 for none; an audio region's end needs ``spt``."""
    ends = []
    for loc in regions:
        if loc.audio:
            if spt is None:
                raise ValueError("the project's sample rate is unknown; an audio region's end in ticks needs it")
            ends.append(loc.audio.start + round(loc.audio.frames / spt))
        elif loc.midi:
            ends.append(loc.midi.start + loc.midi.length)
    return max(ends, default=0)
