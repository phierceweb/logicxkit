"""`chains`: put the tracking chains on a project's channels. Writes a copy; `--plan` prints.

Split from `cli.py` for size. The plan path reads the source and writes nothing, so a run on an
already-dialled song can be inspected before it replaces anything.
"""

from __future__ import annotations

from pathlib import Path

from pf_core.exceptions import PreconditionError
from pf_core.utils.io import atomic_write_bytes

from .services.chains import (
    base_donors,
    chain_plan,
    describe_duplicates,
    duplicate_chain_slots,
    load_chain_config,
    load_extra_donors,
    verify_strip_values,
    width_plan,
)
from ._edit import _discard
from .services.chain_report import chain_changes
from .services.donors import load_donor_library
from .services.insert import insert_slots, project_records, widen_channels
from .services.integrity import regressions
from .services.retrack import copy_project, find_project

_REPORT_LABELS = (("unmatched", "no chain configured"),
                  ("missing_from_project", "configured but absent here"),
                  ("degraded", "wanted a plugin with no donor"),
                  ("shape_mismatch", "CHAIN DIFFERS FROM ITS SOURCE STRIP"))


def _prepare(data: bytes, cfg: dict, library: Path) -> dict:
    """Everything up to the write: widen, pick donors, plan, patch, read back."""
    data, widened = widen_channels(data, width_plan(data, cfg))
    version = next((r.ver for r in project_records(data) if r.tag == b"UCuA"), None)
    eq_donor, comp_donor, from_library = base_donors(data, version, library)
    extra, derived = load_extra_donors(cfg, version, library)
    plan, report = chain_plan(data, cfg, eq_donor, comp_donor,
                              env_donor=extra.get("enveloper", (None, None))[0], extra=extra)

    patched = insert_slots(data, plan)
    dupes = duplicate_chain_slots(patched, plan)
    if dupes:
        drop: dict[int, set[int]] = {}
        for owner, key, _type_id in dupes:
            drop.setdefault(owner, set()).add(key)
        patched = insert_slots(data, plan, drop=drop)
    return {
        "data": data, "patched": patched, "plan": plan, "report": report,
        "changes": chain_changes(data, plan), "widened": widened, "version": version,
        "eq": eq_donor, "comp": comp_donor, "from_library": from_library,
        "derived": derived, "missing": [n for n in (cfg.get("donors") or {}) if n not in extra],
        "dupes": describe_duplicates(patched, dupes),
        "drift": verify_strip_values(patched, cfg) + describe_duplicates(
            patched, duplicate_chain_slots(patched, plan)),
    }


def _print_context(p: dict, library: Path) -> None:
    if p["widened"]:
        print(f"  widened to stereo: {len(p['widened'])} channel(s)")
    print(f"  class v{p['version']} · library {len(load_donor_library(library))} donor(s) · "
          f"EQ {'ok' if p['eq'] else 'MISSING'} · Comp {'ok' if p['comp'] else 'MISSING'}")
    if p["from_library"]:
        print(f"  donor library supplied: {', '.join(p['from_library'])} (absent from this project)")
    if p["missing"]:
        print(f"  no donor at v{p['version']}: {', '.join(p['missing'])}")
    if p["derived"]:
        print(f"  ⚠️  DERIVED v{p['version']} donor(s) — never observed at this version, "
              f"open in Logic to confirm: {', '.join(sorted(p['derived']))}")
    for key, label in _REPORT_LABELS:
        if p["report"][key]:
            print(f"    {label}: {', '.join(p['report'][key])}")
    for line in p["dupes"]:
        print(f"    dropped: {line}")


def _print_changes(changes: list) -> int:
    """The chains that would go on, and what they would take off. -> channels being replaced."""
    losing = [c for c in changes if c.replaced]
    for change in changes:
        print("    " + change.line())
    if losing:
        print(f"\n  ⚠️  {len(losing)} channel(s) already carry a chain that would be REPLACED:")
        for c in losing:
            print(f"       {c.ref:26s} loses {' -> '.join(c.replaced)}")
        print("      The input is never written; this is what the copy loses.")
    return len(losing)


def _apply_chains(dest: Path, cfg, library: Path, *, strict: bool) -> int:
    """Patch every alternative in the copy. Raises before or after any write; the caller
    discards the whole copy, so a refusal never leaves a half-patched bundle."""
    total = 0
    for data_file in sorted(dest.glob("Alternatives/*/ProjectData")):
        p = _prepare(data_file.read_bytes(), cfg, library)
        _print_context(p, library)
        _print_changes(p["changes"])
        if p["drift"]:
            raise PreconditionError("refusing to write: the patched project read back wrong:\n  "
                                    + "\n  ".join(p["drift"]))
        if strict and p["report"]["shape_mismatch"]:
            raise PreconditionError(
                "refusing to write (--strict): a chain differs from its source strip:\n  "
                + "\n  ".join(p["report"]["shape_mismatch"]))
        broke = regressions(p["data"], p["patched"])
        if broke:
            raise PreconditionError(
                "refusing to write: the chain edit broke structure the input had right:\n  "
                + "\n  ".join(broke))
        atomic_write_bytes(data_file, p["patched"])
        if data_file.read_bytes() != p["patched"]:
            raise PreconditionError(f"{data_file.parent.name}: the bytes on disk are not the "
                                    "bytes that passed the gate")
        applied = sum(len(v) for v in p["plan"].values())
        total += applied
        print(f"  {data_file.parent.name}: {len(p['plan'])} channel(s), {applied} slot(s); "
              f"{len(p['data'])} -> {len(p['patched'])} bytes")
    return total


def cmd_chains(args) -> int:
    if not args.plan and not args.out:
        print("  --out is required unless you pass --plan")
        return 2
    cfg = load_chain_config(Path(args.config))
    from ..utils.data import data_dir
    library = Path(args.library) if args.library else data_dir("donors")

    if args.plan:
        project = find_project(Path(args.project))
        print(f"in  : {project}\n")
        losing = 0
        for data_file in sorted(project.glob("Alternatives/*/ProjectData")):
            p = _prepare(data_file.read_bytes(), cfg, library)
            _print_context(p, library)
            losing += _print_changes(p["changes"])
            if p["drift"]:
                print("\n  would REFUSE — the patched project reads back wrong:")
                for line in p["drift"]:
                    print(f"    {line}")
        print(f"\n{'Nothing would be replaced.' if not losing else str(losing) + ' channel(s) would lose a chain.'}")
        return 0

    copied = copy_project(Path(args.project), Path(args.out))
    dest = copied["dest"]
    print(f"in  : {copied['source']}\nout : {dest}\n")

    try:
        total = _apply_chains(dest, cfg, library, strict=args.strict)
    except PreconditionError:
        # An earlier alternative may already be patched; a half-written bundle is worse than none.
        _discard(copied["dest_root"])
        raise
    if not total:
        print("\nNOTHING APPLIED — check the config's reference names against `logic project`.")
        return 1
    print(f"\nApplied {total} plugin slot(s).")
    return 0


def register(sub) -> None:
    ap = sub.add_parser("chains", help="apply native tracking chains to a project copy")
    ap.add_argument("project", help="the ORIGINAL project (read for donors + layout)")
    ap.add_argument("--out", help="directory holding the copy to modify")
    ap.add_argument("--config", required=True, help="JSON chain config")
    ap.add_argument("--library", default=None, help="donor library directory (default: the data root's donors/)")
    ap.add_argument("--plan", action="store_true", help="print what would change and stop")
    ap.add_argument("--strict", action="store_true",
                    help="refuse when a chain differs from its source strip")
    ap.set_defaults(func=cmd_chains)
