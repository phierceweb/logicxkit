"""Apply native tracking chains to a project's channels.

Channels are matched by the channel-strip **reference** they carry (`Kick In.cst`), so one
config works across every session regardless of channel numbering, or by a channel name
(`chains_channels`). The plug-in records come from `chain_donors`: clones from inside the target
project, else the donor library at the project's own class version; parameter values from a
saved strip when the config names one, else from a JSON description. `chain_checks` reads a
written project back.
"""

from __future__ import annotations

import re
from pathlib import Path

from .sidechain import with_side_chain
from .chain_donors import COMP_TYPE, ENV_TYPE, EQ_TYPE, id_offsets_for, strip_chain, strip_params, strip_path
from .chains_channels import CHANNEL_NAMES, channel_name, plan_channels, resolve_params  # noqa: F401
from .comp import build_comp
from .eq import build_eq
from .slots import slot_index_base
from ..stream.stream import project_records

REF_MAX = 400  # a channel's reference record is small; plugin slots are far bigger
_REF = re.compile(rb"[\x20-\x7e]{2,60}\.cst")
EQ_USER_FLOATS, COMP_USER_FLOATS = 33, 15   # what build_eq/build_comp emit
# (type, older count, current count): the older block is the current one minus trailing floats,
# so its floats copy positionally and the donor's tail stands. Channel EQ: class v2 vs v3+.
OLDER_LAYOUTS = {(EQ_TYPE, 51, 52)}


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


def width_plan(data: bytes, config: dict) -> dict[int, int]:
    """owner -> channel width, for chains whose config declares one (``"stereo": true``).

    A send return built mono gives every plugin on it a mono instance, since a slot's width
    follows its channel's. Declaring it here fixes the channel, and the slots follow.
    """
    from .slot_width import MONO, STEREO

    from .chains_channels import owners_by_label

    chains = config["chains"]
    out = {}
    for owner, ref in channel_references(data).items():
        spec = chains.get(ref)
        if spec and "stereo" in spec:
            out[owner] = STEREO if spec["stereo"] else MONO
    by_label = owners_by_label(data)
    for name, spec in chains.items():
        if not name.endswith(".cst") and "stereo" in spec:
            for owner in by_label.get(CHANNEL_NAMES.get(name, name), []):
                out[owner] = STEREO if spec["stereo"] else MONO
    return out


def chain_plan(data: bytes, config: dict, eq_donor: bytes | None, comp_donor: bytes | None,
               env_donor: bytes | None = None, env_pool: list[bytes] | None = None,
               extra: dict[str, tuple[bytes, int]] | None = None):
    """Build an ``insert_slots`` plan from a config keyed by channel-strip reference."""
    chains = config["chains"]
    refs = channel_references(data)
    plan, matched, degraded, mismatched, older = {}, set(), [], [], []

    from ..._binary import find_blocks
    from .insert import instance_offsets
    ids = {EQ_TYPE: id_offsets_for(data, EQ_TYPE), COMP_TYPE: id_offsets_for(data, COMP_TYPE)}
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
                              id_offsets_for(data, tid, raw), tid,
                              False, resolve_params(tid, params.get(name, {}), f"{ref}: {name}", raw)))
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
                              id_offsets_for(data, tid, raw), tid,
                              False, resolve_params(tid, params.get(name, {}), f"{ref}: {name}", raw)))
                key += 1
        if slots:
            # a donor's side chain names a channel of the project it was saved from
            plan[owner] = [(with_side_chain(entry[0], None), *entry[1:]) for entry in slots]
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
            if not blocks or blocks[0][2] == len(floats):
                continue
            line = (f"{ref}: {tid} source has {len(floats)} floats, donor holds "
                    f"{blocks[0][2]} — trailing {blocks[0][2] - len(floats)} kept from donor")
            (older if (tid, len(floats), blocks[0][2]) in OLDER_LAYOUTS else mismatched).append(line)

    by_name, named = plan_channels(data, config, extra, id_offsets_for)
    twice = sorted(set(plan) & set(by_name))
    if twice:
        raise ValueError("channel(s) keyed twice, by strip reference and by name: "
                         + ", ".join(f"{refs[o]} / {channel_name(data, o)}" for o in twice))
    plan.update(by_name)
    matched |= named
    return plan, {
        "matched": sorted(matched),
        "unmatched": sorted({r for r in refs.values() if r not in chains}),
        "missing_from_project": sorted(set(chains) - set(refs.values()) - matched),
        "degraded": sorted(set(degraded)),
        "shape_mismatch": sorted(set(mismatched)),
        "older_layout": sorted(set(older)),
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
