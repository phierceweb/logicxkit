"""`quantize-drums`: quantize a multitrack drum take on a copy, without Logic."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from ._edit import CommandError, edit_copy
from .services.regions.flexmarkers import GRIDS


def _members(data: bytes, args, count: int | None) -> list[str]:
    if args.track:
        return list(args.track)
    from .services.arrange.stacks import read_stacks, rows_below
    from .services.arrange.trackname import stack_named
    stacks = read_stacks(data, count)
    stack = stack_named(stacks, args.stack)
    if stack is None:
        raise CommandError(f"no folder stack named {args.stack!r}; name the tracks with --track")
    names = [name for _key, name in rows_below(stacks, stack, headers=False)]
    if not names:
        raise CommandError(f"stack {args.stack!r} has no member tracks")
    return names


def _prefix(name: str) -> str:
    """The track a recording was named after: 'Kick In#04' and 'Kick In: Take 2' -> 'Kick In'."""
    return name.split("#")[0].split(":")[0].strip()


def _wav_finder(project_file: Path, audio_dir: str | None):
    """A region's WAV: a file named after the region (the record paired with it when that
    agrees, else the latest take), looked for where the file record says, beside the project
    folder, in the bundle's Media, and under --audio; a region without a same-named file
    falls back to its paired record."""
    bundle = project_file.parents[2]
    folders = [Path(audio_dir)] if audio_dir else []
    folders += [bundle.parent / "Audio Files", bundle / "Media" / "Audio Files"]

    def find(region):
        if region.file is None:
            return None
        places = [Path(region.file.folder), *folders]
        paired = next((f / region.file.name for f in places if (f / region.file.name).exists()), None)
        want = _prefix(region.name)
        if paired is not None and _prefix(paired.stem) == want:
            return paired
        same = sorted({p for f in places if f.is_dir() for p in f.glob("*.wav") if _prefix(p.stem) == want}, key=lambda p: p.name)
        return same[-1] if same else paired
    return find


def bar_range(text: str) -> tuple[int, int]:
    """``17-24`` or ``17``: song bars, both ends included."""
    m = re.fullmatch(r"\s*(\d+)\s*(?:-\s*(\d+)\s*)?", text)
    if not m:
        raise argparse.ArgumentTypeError(f"{text!r}: bars as FIRST-LAST, e.g. 17-24")
    first = int(m.group(1))
    return first, int(m.group(2) or first)


def cmd_quantize(args) -> int:
    from .services.regions.quantize_drums import quantize_drums

    if not args.out:
        print("  --out is needed to write")
        return 2

    def step(data, count, project_file):
        members = _members(data, args, count)
        refs = list(args.ref)
        data, report = quantize_drums(data, members=members, references=refs, wav_of=_wav_finder(Path(project_file), args.audio),
                                      grid=args.grid, group=args.group, groups_off=tuple(args.off), track_count=count,
                                      bars=args.bars)
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
    qp = sub.add_parser("quantize-drums", help="quantize a multitrack drum take to a grid on a copy, "
                        "without Logic: the drum group, Q-Reference, flex Slicing, the markers")
    qp.add_argument("project")
    qp.add_argument("--out", help="output directory (needed to write)")
    qp.add_argument("--stack", default="Drums", help="folder stack whose member tracks are the drums (default Drums)")
    qp.add_argument("--track", action="append", metavar="TRACK", help="a member track instead of --stack (repeatable)")
    qp.add_argument("--ref", nargs="+", default=["Kick In", "Snare Up"], metavar="TRACK",
                    help="the tracks whose hits set the moves (default Kick In, Snare Up)")
    qp.add_argument("--grid", type=int, help=f"1/N note grid: {', '.join(map(str, GRIDS[:-1]))} or {GRIDS[-1]} "
                    "(default 16; with --bars, each region's own Quantize value)")
    qp.add_argument("--bars", type=bar_range, metavar="FIRST-LAST", help="re-quantize only the hits in these song "
                    "bars; every other marker keeps its bytes")
    qp.add_argument("--group", default="Drums", help="the drum group's name (reused when every member is in it)")
    qp.add_argument("--off", nargs="*", default=["OH", "Room"], metavar="GROUP", help="groups to switch off first")
    qp.add_argument("--audio", metavar="DIR", help="a folder holding the regions' audio files, when they are not "
                    "where the project says")
    qp.set_defaults(func=cmd_quantize)
