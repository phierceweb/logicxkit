"""Apply native tracking chains to a project's channels.

Channels are matched by the channel-strip **reference** they carry (`Kick In.cst`), so one
config works across every session regardless of channel numbering. The plugin records themselves
are cloned from donors **inside the target project**, so the record class version always matches
the Logic build that wrote it.

When the project holds no instance of a plugin at all, the donor library supplies one at the
project's own class version (``base_donors`` for EQ/Compressor, ``load_extra_donors`` for the
rest). A version the library cannot match is dropped rather than transplanted.

Parameter VALUES come from a saved strip whenever the config names one (``strip``). Deriving
them from a JSON description is the fallback for a channel with no strip, because a derived
curve is a guess and the saved strip is the ground truth.
"""

from __future__ import annotations

import re
from pathlib import Path

from .comp import build_comp
from .eq import build_eq
from .insert import project_records, slot_index_base

REF_MAX = 400  # a channel's reference record is small; plugin slots are far bigger
_REF = re.compile(rb"[\x20-\x7e]{2,60}\.cst")
EQ_TYPE, COMP_TYPE, ENV_TYPE = 236, 154, 157
EQ_USER_FLOATS, COMP_USER_FLOATS = 33, 14   # what build_eq/build_comp emit


def channel_references(data: bytes) -> dict[int, str]:
    """owner -> the channel-strip reference it carries."""
    out: dict[int, str] = {}
    for record in project_records(data):
        if record.tag != b"UCuA" or len(record.raw) - 36 >= REF_MAX:
            continue
        match = _REF.search(record.raw)
        if match and record.owner not in out:
            out[record.owner] = match.group().decode("latin-1")
    return out


def find_donors(data: bytes) -> tuple[bytes | None, bytes | None]:
    """The smallest Channel EQ and Compressor slot records in the project, to clone from."""
    from .._binary import find_blocks

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
    """Channel EQ and Compressor donors -> ``(eq, comp, [names taken from the library])``.

    The project's own records win: their class version is correct by construction. The library
    is the fallback for a session that contains the plugin nowhere — without it every chain
    wanting that plugin is silently degraded instead.
    """
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
    """A saved .cst's chain in slot order: ``[(plugin type id, every parameter float)]``.

    The whole array is taken, not the user-parameter prefix build_eq/build_comp emit: the
    per-instance id lives past the chunk (see ``instance_offsets``), so every float in it is a
    parameter and copying all of them reproduces the sound without carrying identity across.
    """
    from .._binary import find_blocks, read_block_floats
    from .records import read_records

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
    """Pull a plugin-slot record of ``type_id`` out of a saved .cst, with its class version.

    Some plugins exist in no session on disk — the Enveloper lives only in the user's saved
    tracking strips. Transplanting is safe only when the version matches the target project,
    so the caller gets it back to check.
    """
    import struct

    from .._binary import find_blocks
    from .records import read_records

    for record in read_records(Path(path).read_bytes()):
        if record.tag != b"UCuA":
            continue
        blocks = find_blocks(record.payload)
        if blocks and blocks[0][1] == type_id:
            return record.raw, struct.unpack_from("<H", record.raw, 4)[0]
    return None, None


def _id_offsets_for(data: bytes, type_id: int, extra: bytes | None = None) -> tuple[int, ...]:
    """Per-instance id offsets for one plugin, MEASURED from every instance available.

    Position is plugin-specific, so it is never assumed: with fewer than two instances the
    result is empty and the clone is copied verbatim rather than being written at a guess.
    """
    from .._binary import find_blocks
    from .insert import instance_offsets, project_records

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
                      library: Path | None = None) -> dict[str, tuple[bytes, int]]:
    """Donors the config declares -> ({name: (record, type id)}, [names that were DERIVED]).

    Sourced from the persistent donor library by default, falling back to a named .cst, and
    finally to a v5 record retargeted down (``retarget_version``) — the only way a v3 session
    gets a native reverb, since no v3 project on disk contains one. A version that can be
    neither matched nor derived is dropped rather than transplanted; the caller reports it.
    """
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


def _values(source: dict, spec: dict, type_id: int, json_key: str, build, user_floats: int):
    """Parameter floats for one plugin: the named strip's whole array, else the JSON block.

    A strip wins outright — it is what the user actually dialled, and its array covers parameters
    build_eq/build_comp never emit.
    """
    if type_id in source:
        return source[type_id], len(source[type_id])
    if json_key in spec:
        return build(spec[json_key]), user_floats
    return None, 0


def verify_strip_values(data: bytes, config: dict) -> list[str]:
    """Every strip-sourced float in a WRITTEN project, checked against the strip it came from.

    The build reporting success is not evidence the values landed: cloning a donor verbatim
    shipped a factory Enveloper into three projects while every count and validation passed.
    This reads the result back instead.
    """
    from .._binary import find_blocks, read_block_floats
    from .insert import project_records

    chains = config["chains"]
    refs = channel_references(data)
    by_owner: dict[int, list[tuple[int, int, list[float]]]] = {}
    for record in project_records(data):
        if record.tag != b"UCuA" or b"GAMETSPP" not in record.raw:
            continue
        blocks = find_blocks(record.raw[36:])
        if blocks:
            idx, type_id, n = blocks[0]
            by_owner.setdefault(record.owner, []).append(
                (record.key, type_id, read_block_floats(record.raw[36:], idx, n)))

    problems = []
    for owner, ref in sorted(refs.items()):
        spec = chains.get(ref)
        if not spec or not spec.get("strip"):
            continue
        want = strip_params(strip_path(config, spec))
        for _key, type_id, got in sorted(by_owner.get(owner, [])):
            expected = want.get(type_id)
            if expected is None:
                continue
            n = min(len(expected), len(got))
            if got[:n] != expected[:n]:
                off = [i for i in range(n) if got[i] != expected[i]]
                problems.append(f"{ref}: plugin {type_id} differs from its strip at "
                                f"float(s) {off[:6]}")
    return problems


def width_plan(data: bytes, config: dict) -> dict[int, int]:
    """owner -> channel width, for chains whose config declares one (``"stereo": true``).

    A send return built mono gives every plugin on it a mono instance, since a slot's width
    follows its channel's. Declaring it here fixes the channel, and the slots follow.
    """
    from .insert import MONO, STEREO

    chains = config["chains"]
    out = {}
    for owner, ref in channel_references(data).items():
        spec = chains.get(ref)
        if spec and "stereo" in spec:
            out[owner] = STEREO if spec["stereo"] else MONO
    return out


def duplicate_chain_slots(data: bytes, plan: dict) -> list[tuple[int, int, int]]:
    """``(owner, slot key, plugin type id)`` for chain-placed plugins left twice on a channel.

    The plan overwrites slot keys from the project's first slot key up; a channel whose own chain sat at
    higher keys keeps those records. A survivor of a type the chain also places is the
    superseded copy of that plugin, and leaving it puts two in series — every count still adds
    up and the run reports success, so only a read-back catches it.
    """
    from .._binary import find_blocks
    from .insert import project_records

    placed: dict[int, tuple[set[int], set[int]]] = {}
    for owner, entries in plan.items():
        types, keys = set(), set()
        for entry in entries:
            keys.add(entry[1])
            blocks = find_blocks(entry[0][36:])
            if blocks:
                types.add(blocks[0][1])
        placed[owner] = (types, keys)

    found = []
    for record in project_records(data):
        if record.tag != b"UCuA" or b"GAMETSPP" not in record.raw:
            continue
        types, keys = placed.get(record.owner, (set(), set()))
        if record.key in keys:
            continue
        blocks = find_blocks(record.raw[36:])
        if blocks and blocks[0][1] in types:
            found.append((record.owner, record.key, blocks[0][1]))
    return sorted(found)


def describe_duplicates(data: bytes, dupes: list[tuple[int, int, int]]) -> list[str]:
    """Duplicate slots as one reportable line each, named by the channel's strip reference."""
    refs = channel_references(data)
    return [f"{refs.get(owner, f'owner {owner}')}: plugin {type_id} also survives at slot key "
            f"{key} — superseded copy of one the chain places" for owner, key, type_id in dupes]


def chain_plan(data: bytes, config: dict, eq_donor: bytes | None, comp_donor: bytes | None,
               env_donor: bytes | None = None, env_pool: list[bytes] | None = None,
               extra: dict[str, tuple[bytes, int]] | None = None):
    """Build an ``insert_slots`` plan from a config keyed by channel-strip reference."""
    chains = config["chains"]
    refs = channel_references(data)
    plan, matched, degraded, mismatched = {}, set(), [], []

    from .._binary import find_blocks
    from .insert import instance_offsets
    ids = {EQ_TYPE: _id_offsets_for(data, EQ_TYPE), COMP_TYPE: _id_offsets_for(data, COMP_TYPE)}
    if env_pool and len(env_pool) >= 2:
        blocks = find_blocks(env_pool[0])
        ids[ENV_TYPE] = tuple(instance_offsets(
            env_pool, blocks[0][0] + 12 + blocks[0][2] * 4)) if blocks else ()
    else:
        ids[ENV_TYPE] = ()
    extra = extra or {}

    for owner, ref in sorted(refs.items()):
        spec = chains.get(ref)
        if spec is None:
            continue
        label = f"{config.get('label_prefix', 'Trk')} - {spec.get('label', ref.removesuffix('.cst'))}"
        source = strip_params(strip_path(config, spec)) if spec.get("strip") else {}
        slots, key = [], slot_index_base(data)          # 2 in projects made before Logic 11.2
        wanted_extra = list(spec.get("pre", [])) + list(spec.get("post", []))
        missing_extra = [n for n in wanted_extra if n not in extra]
        params = spec.get("params", {})

        eq_floats, eq_limit = _values(source, spec, EQ_TYPE, "eq", build_eq, EQ_USER_FLOATS)
        comp_floats, comp_limit = _values(source, spec, COMP_TYPE, "comp", build_comp,
                                          COMP_USER_FLOATS)

        for name in spec.get("pre", []):
            if name in extra:
                raw, tid = extra[name]
                floats = source.get(tid)
                slots.append((raw, key, floats, len(floats or ()), label,
                              _id_offsets_for(data, tid, raw), tid,
                              False, {int(k): v for k, v in params.get(name, {}).items()}))
                key += 1
        if eq_floats is not None and eq_donor:
            slots.append((eq_donor, key, eq_floats, eq_limit, label, ids[EQ_TYPE], EQ_TYPE))
            key += 1
        if spec.get("env") and env_donor:
            # Transient shaping sits between EQ and compression. The donor supplies a record
            # of the project's own class version, the strip supplies the values: a v3 library
            # donor carries factory defaults, so taking it verbatim loses the strip's.
            env_floats = source.get(ENV_TYPE)
            slots.append((env_donor, key, env_floats, len(env_floats or ()), label,
                          ids[ENV_TYPE], ENV_TYPE, "env" in spec.get("bypass", [])))
            key += 1
        if comp_floats is not None and comp_donor:
            slots.append((comp_donor, key, comp_floats, comp_limit, label,
                          ids[COMP_TYPE], COMP_TYPE))
            key += 1
        for name in spec.get("post", []):
            if name in extra:
                raw, tid = extra[name]
                floats = source.get(tid)
                slots.append((raw, key, floats, len(floats or ()), label,
                              _id_offsets_for(data, tid, raw), tid,
                              False, {int(k): v for k, v in params.get(name, {}).items()}))
                key += 1
        if slots:
            plan[owner] = slots
            matched.add(ref)
        if ((eq_floats is not None and not eq_donor)
                or (comp_floats is not None and not comp_donor)
                or (spec.get("env") and not env_donor) or missing_extra):
            degraded.append(ref)
        # A chain built from a strip must reproduce that strip's plugin order; drift here means
        # the config dropped or reordered a plugin the strip carries.
        if source and not missing_extra:
            want = [tid for tid, _f in strip_chain(strip_path(config, spec))]
            got = [entry[6] for entry in slots]
            if want != got:
                mismatched.append(f"{ref}: strip {want} != plan {got}")
        # a shorter source chunk leaves the donor's trailing floats in place; say so rather than
        # letting a silent partial write pass as a verbatim copy
        for donor, floats, tid in ((eq_donor, eq_floats, EQ_TYPE),
                                   (comp_donor, comp_floats, COMP_TYPE)):
            if donor is None or floats is None or tid not in source:
                continue
            blocks = find_blocks(donor[36:])
            if blocks and blocks[0][2] != len(floats):
                mismatched.append(
                    f"{ref}: {tid} source has {len(floats)} floats, donor holds "
                    f"{blocks[0][2]} — trailing {blocks[0][2] - len(floats)} kept from donor")

    return plan, {
        "matched": sorted(matched),
        "unmatched": sorted({r for r in refs.values() if r not in chains}),
        "missing_from_project": sorted(set(chains) - set(refs.values())),
        "degraded": sorted(set(degraded)),
        "shape_mismatch": sorted(set(mismatched)),
    }


def load_chain_config(path: Path) -> dict:
    import json
    cfg = json.loads(Path(path).read_text())
    if "chains" not in cfg:
        raise ValueError("config needs a 'chains' object keyed by channel-strip reference")
    for ref, spec in cfg["chains"].items():
        clash = [k for k in ("eq", "comp") if spec.get("strip") and k in spec]
        if clash:
            raise ValueError(f"{ref}: sets 'strip' and {clash} — the strip already supplies "
                             "those values; drop the JSON block")
    return cfg
