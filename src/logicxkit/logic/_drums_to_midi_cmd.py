"""`drums-to-midi`: drum hits in audio tracks to notes in a MIDI region, on a copy, without Logic."""

from __future__ import annotations

from pathlib import Path

from ._edit import CommandError, edit_copy
from ._quantize_cmd import _wav_finder


def parse_hits(specs: list[str] | None) -> list[tuple[str, str, float | None]]:
    """``TRACK=TERM[:THRESHOLD]`` specs -> (track, term, the track's own floor in dB or None); a term is
    lower-cased with its spaces collapsed."""
    out = []
    for spec in specs or []:
        track, sep, term = spec.rpartition("=")
        term, colon, floor = term.rpartition(":")
        if not colon or not _number(floor):
            term, floor = term + colon + floor, None
        term = " ".join(term.split()).lower()
        if not sep or not track.strip() or not term:
            raise CommandError(f"bad --hit {spec!r}: TRACK=TERM[:THRESHOLD]")
        if floor is not None and float(floor) > 0:
            raise CommandError(f"bad --hit {spec!r}: the threshold is dB under the track's loudest hit, 0 or below")
        out.append((track.strip(), term, None if floor is None else float(floor)))
    return out


def _number(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


def parse_velocity(spec: str | None) -> tuple[int, int, float]:
    """``FLOOR..CEILING[:GAMMA]`` -> the band the hits' velocities map onto; (1, 127, 1.0) without it."""
    if spec is None:
        return 1, 127, 1.0
    band, _, gamma = spec.partition(":")
    lo, dots, hi = band.partition("..")
    try:
        floor, ceiling, curve = int(lo), int(hi), float(gamma) if gamma else 1.0
    except ValueError:
        dots = ""
    if not dots or not 1 <= floor <= ceiling <= 127 or not curve > 0:
        raise CommandError(f"bad --velocity {spec!r}: FLOOR..CEILING[:GAMMA], 1 <= FLOOR <= CEILING <= 127, GAMMA above 0")
    return floor, ceiling, curve


def detector_of(args):
    """The onset detector, its floor under the track's loudest hit moved by ``--threshold``."""
    from .services.regions.onsets import Detector

    if args.threshold is None:
        return Detector()
    if args.threshold > 0:
        raise CommandError(f"--threshold {args.threshold:g}: dB under the track's loudest hit, 0 or below")
    return Detector(floor_db=args.threshold)


def cmd_drums_to_midi(args) -> int:
    from groovebin.transforms import grid_ticks

    from .services.midi.drums_to_midi import drums_to_midi, note_for
    from .services.song.events import PPQ

    if not args.out:
        print("  --out is needed to write")
        return 2
    try:
        parsed = parse_hits(args.hit)
        hits = [(track, term) for track, term, _floor in parsed]
        floors = {track: floor for track, _term, floor in parsed if floor is not None}
        velocity = parse_velocity(args.velocity)
        detector = detector_of(args)
        for _track, term in hits:
            note_for(args.map, term)
        if args.grid is not None:
            grid_ticks(args.grid, PPQ)
    except (CommandError, ValueError) as e:
        print(f"  {e}")
        return 2

    def step(data, count, project_file):
        data, report = drums_to_midi(data, hits=hits, target=args.track, wav_of=_wav_finder(Path(project_file), args.audio),
                                     map_name=args.map, grid=args.grid, detector=detector, floors=floors, velocity=velocity,
                                     track_count=count)
        for line in report.lines():
            print(f"  {project_file.parent.name}: {line}")
        return data

    try:
        edit_copy(Path(args.project), Path(args.out), step)
    except (CommandError, ValueError) as e:
        print(f"  {e}")
        return 1
    return 0


def register(sub) -> None:
    from groovebin.maps import NAMES

    from .services.regions.onsets import Detector

    dp = sub.add_parser("drums-to-midi", help="drum hits in audio tracks to notes in a new MIDI region on a software "
                        "instrument track, on a copy, without Logic")
    dp.add_argument("project")
    dp.add_argument("--out", help="output directory (needed to write)")
    dp.add_argument("--hit", action="append", required=True, metavar="TRACK=TERM[:THRESHOLD]",
                    help="an audio track and the drum map term its hits play: kick, snare, hihat closed ...; THRESHOLD is that "
                         "track's own floor in dB under its loudest hit, instead of --threshold (repeatable)")
    dp.add_argument("--velocity", metavar="FLOOR..CEILING[:GAMMA]",
                    help="the band the hits' velocities land in, quietest to loudest (default 1..127); GAMMA above 1 pushes "
                         "the middle down, below 1 lifts it")
    dp.add_argument("--track", required=True, metavar="TARGET", help="the software instrument track the region goes on")
    dp.add_argument("--map", choices=NAMES, default="addictive-drums-2",
                    help="the drum map the terms resolve in (default addictive-drums-2)")
    dp.add_argument("--grid", type=int, metavar="N", help="quantize the notes to 1/N (1, 2, 4, 8, 16, 32 or 64); else the take's timing is kept")
    dp.add_argument("--threshold", type=float, metavar="DB",
                    help=f"a hit is at most DB under the track's loudest hit (default {Detector.floor_db:g}); "
                    "lower finds quieter hits")
    dp.add_argument("--audio", metavar="DIR", help="a folder holding the regions' audio files, when they are not "
                    "where the project says")
    dp.set_defaults(func=cmd_drums_to_midi)
