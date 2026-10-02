"""`donors`: harvest plug-in slot donors from a project, a strip or a folder of strips into the
library — Logic's own plug-ins and, from a project, third-party ones too. Into the data root, a
plug-in the package ships is left to the package, whose donor wins (`utils.data`)."""

from __future__ import annotations

from pathlib import Path

from ._binary import find_blocks
from .services.donors import harvest_donors
from .services.library import factory_settings
from .services.retrack import find_project


def cmd_donors(args) -> int:
    from ..utils.data import PACKAGED, writable_root
    from .services.plugin_names import native_names
    from .services.plugin_library import WIDTH_NAMES, harvest_au, load_library
    lib = Path(args.library) if args.library else writable_root() / "donors"
    skip = set() if args.library else {p.stem for p in (PACKAGED / "donors").glob("*.slot")}
    skipped: list[str] = []
    names = native_names()
    settings = factory_settings()
    if settings.is_dir():
        for folder in settings.iterdir():
            for preset in list(folder.glob("*.pst"))[:3] if folder.is_dir() else []:
                blocks = find_blocks(preset.read_bytes())
                if blocks:
                    names.setdefault(blocks[0][1], folder.name)
                    break
    total = []
    src = Path(args.project)
    if src.suffix == ".cst":
        total += harvest_donors(src.read_bytes(), lib, names, start=0, refresh=args.refresh, skip=skip, skipped=skipped)
    elif src.is_dir() and src.suffix != ".logicx" and not list(src.glob("*.logicx")):
        for strip in sorted(src.rglob("*.cst")):        # a folder of strips
            total += harvest_donors(strip.read_bytes(), lib, names, start=0, refresh=args.refresh, skip=skip, skipped=skipped)
    else:
        for data_file in sorted(find_project(src).glob("Alternatives/*/ProjectData")):
            data = data_file.read_bytes()
            total += harvest_donors(data, lib, names, refresh=args.refresh, skip=skip, skipped=skipped)
            try:
                total += harvest_au(data, lib, name=args.as_name, refresh=args.refresh)
            except ValueError as e:
                print(f"  {e}")
                return 2
    have = load_library([lib])
    print(f"library: {lib}\n  added {len(total)}: {', '.join(total) or '(nothing new)'}")
    if skipped:
        shipped = {d.key: d for d in load_library([PACKAGED / "donors"])}
        print("  the package's own, not harvested: " + ", ".join(sorted({shipped[k].label if k in shipped else k for k in skipped})))
    print(f"  now holds {len(have)} donor(s):")
    for donor in sorted(have, key=lambda d: d.key):
        label = donor.name or names.get(donor.type_id) or donor.label
        width = f" {WIDTH_NAMES.get(donor.width, donor.width)}" if donor.width else ""
        print(f"    {donor.key:28s} {label:22s} class v{donor.version}{width}")
    return 0


def register(sub) -> None:
    dn = sub.add_parser("donors", help="harvest plugin-slot donors from a project")
    dn.add_argument("project")
    dn.add_argument("--library", default=None, help="donor library (default: the data root's donors/)")
    dn.add_argument("--as", dest="as_name", metavar="[SUBTYPE=]NAME",
                    help="the name for the third-party plug-in harvested; with several in the project, "
                         "name one by its subtype code (FPMb=Pro-MB)")
    dn.add_argument("--refresh", action="store_true",
                    help="replace donors the library already holds (after a plug-in update); kept otherwise")
    dn.set_defaults(func=cmd_donors)
