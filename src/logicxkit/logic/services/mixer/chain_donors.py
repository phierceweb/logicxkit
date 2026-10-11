"""Where a chain's plug-in records and parameter values come from.

Records are cloned from donors inside the target project, so the record class version always
matches the Logic build that wrote it; when the project holds no instance of a plug-in, the donor
library supplies one at the project's own class version (`base_donors` for EQ/Compressor,
`load_extra_donors` for the rest), and a version the library cannot match is dropped rather than
transplanted. Values come from a saved strip (`.cst`) whenever the config names one.
"""

from __future__ import annotations

from pathlib import Path

from ..stream.stream import project_records

EQ_TYPE, COMP_TYPE, ENV_TYPE = 236, 154, 157


def find_donors(data: bytes) -> tuple[bytes | None, bytes | None]:
    """The smallest Channel EQ and Compressor slot records in the project, to clone from."""
    from ..._binary import find_blocks

    best: dict[int, bytes] = {}
    for record in project_records(data):
        if record.tag != b"UCuA" or b"GAMETSPP" not in record.raw:
            continue
        for _idx, type_id, _n in find_blocks(record.raw[36:]):
            if type_id in (EQ_TYPE, COMP_TYPE) and (
                    type_id not in best or len(record.raw) < len(best[type_id])):
                best[type_id] = record.raw
    return best.get(EQ_TYPE), best.get(COMP_TYPE)


def base_donors(data: bytes, version: int | None = None, library: Path | None = None):
    """Channel EQ and Compressor donors -> ``(eq, comp, [names taken from the library])``: the
    project's own records first (their class version is right by construction), the library for
    a plug-in the session holds nowhere."""
    from .donors import donor_key, load_donor_library

    eq, comp = find_donors(data)
    from_library: list[str] = []
    if version is None or library is None:
        return eq, comp, from_library
    lib = load_donor_library(library)
    for type_id, name, have in ((EQ_TYPE, "Channel EQ", eq), (COMP_TYPE, "Compressor", comp)):
        if have is not None:
            continue
        hit = lib.get(donor_key(type_id, version))
        if not hit:
            continue
        if type_id == EQ_TYPE:
            eq = hit[0]
        else:
            comp = hit[0]
        from_library.append(name)
    return eq, comp, from_library


def strip_chain(path: Path) -> list[tuple[int, list[float]]]:
    """A saved .cst's chain in slot order: ``[(plugin type id, every parameter float)]``. Every
    float of a block is a parameter (the instance id sits past it), so all are taken."""
    from ..._binary import find_blocks, read_block_floats
    from ..stream.records import read_records

    out = []
    for record in sorted(read_records(Path(path).read_bytes()), key=lambda r: r.key):
        if record.tag != b"UCuA":
            continue
        blocks = find_blocks(record.payload)
        if blocks:
            idx, type_id, n = blocks[0]
            out.append((type_id, read_block_floats(record.payload, idx, n)))
    return out


def strip_params(path: Path) -> dict[int, list[float]]:
    """``strip_chain`` keyed by plugin type, first slot of each type winning."""
    params: dict[int, list[float]] = {}
    for type_id, floats in strip_chain(path):
        params.setdefault(type_id, floats)
    return params


def strip_path(config: dict, spec: dict) -> Path:
    """Resolve a chain's ``strip`` against the config's ``strip_root``."""
    from .library import resolve

    return resolve(spec["strip"], config.get("strip_root"))


def donor_from_cst(path: Path, type_id: int) -> tuple[bytes | None, int | None]:
    """A plug-in slot record of ``type_id`` out of a saved .cst, with its class version, which
    must match the target project's."""
    import struct

    from ..._binary import find_blocks
    from ..stream.records import read_records

    for record in read_records(Path(path).read_bytes()):
        if record.tag != b"UCuA":
            continue
        blocks = find_blocks(record.payload)
        if blocks and blocks[0][1] == type_id:
            return record.raw, struct.unpack_from("<H", record.raw, 4)[0]
    return None, None


def id_offsets_for(data: bytes, type_id: int, extra: bytes | None = None) -> tuple[int, ...]:
    """Per-instance id offsets for one plug-in, measured from every instance available; empty
    with fewer than two, and the clone is then copied verbatim, never stamped at a guess."""
    from ..._binary import find_blocks
    from .insert import instance_offsets
    from ..stream.stream import project_records

    payloads = []
    for record in project_records(data):
        if record.tag != b"UCuA" or b"GAMETSPP" not in record.raw:
            continue
        payload = record.raw[36:]
        blocks = find_blocks(payload)
        if blocks and blocks[0][1] == type_id:
            payloads.append(payload)
    if extra:
        payloads.append(extra[36:])
    if len(payloads) < 2:
        return ()
    sizes = {}
    for payload in payloads:
        sizes.setdefault(len(payload), []).append(payload)
    same = max(sizes.values(), key=len)
    blocks = find_blocks(same[0])
    chunk_end = blocks[0][0] + 12 + blocks[0][2] * 4
    return tuple(instance_offsets(same, chunk_end))


def load_extra_donors(config: dict, project_version: int | None = None,
                      library: Path | None = None) -> tuple[dict[str, tuple[bytes, int]], list[str]]:
    """Donors the config declares -> ({name: (record, type id)}, [names that were derived]): the
    library at the project's version first, else a named .cst, else a v5 record retargeted down
    (``retarget_version``); one neither matched nor derived is dropped and reported."""
    from .donors import donor_key, load_donor_library, retarget_version
    from .library import resolve

    lib = load_donor_library(library) if library else {}
    out: dict[str, tuple[bytes, int]] = {}
    derived: list[str] = []
    for name, spec in (config.get("donors") or {}).items():
        type_id = spec["type"]
        if project_version is not None:
            hit = lib.get(donor_key(type_id, project_version))
            if hit:
                out[name] = (hit[0], type_id)
                continue
        if spec.get("cst"):
            raw, ver = donor_from_cst(resolve(spec["cst"], config.get("strip_root")), type_id)
            if raw is not None and (project_version is None or ver == project_version):
                out[name] = (raw, type_id)
                continue
        donor = lib.get(donor_key(type_id, 5))
        if donor and project_version is not None:
            try:
                out[name] = (retarget_version(donor[0], project_version), type_id)
                derived.append(name)
            except ValueError:
                pass          # not derivable — reported as a missing donor instead
    return out, derived
