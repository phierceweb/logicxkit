"""Chains keyed by a channel name rather than a strip reference — the Stereo Out's mastering
chain: its plug-ins in slot order from declared donors, each parameter named as
`output_params` names it or given by float index, checked against the donor's own block, and
read back from the written project afterwards."""

from __future__ import annotations

from ..._binary import find_blocks, read_block_floats
from .binding import channels
from .slots import slot_index_base
from ..stream.stream import HEADER, project_records
from .output_params import NAMES, PARAMS, set_params

# The inspector's name for a channel the mixer labels otherwise.
CHANNEL_NAMES = {"Stereo Out": "Output 1-2"}
LABELS = {v: k for k, v in CHANNEL_NAMES.items()}
TOLERANCE = 1e-5                        # a float32 read back against the config's decimal


def channel_name(data: bytes, owner: int) -> str:
    """What a report calls a channel with no strip reference: its config name or mixer label."""
    c = channels(data).get(owner)
    return LABELS.get(c.label, c.label) if c else f"owner {owner}"


def owners_by_label(data: bytes) -> dict[str, list[int]]:
    out: dict[str, list[int]] = {}
    for owner, c in channels(data).items():
        out.setdefault(c.label, []).append(owner)
    return out


def _block(donor: bytes) -> tuple[int, int, list[float]]:
    blocks = find_blocks(donor[HEADER:])
    if not blocks:
        return 0, 0, []
    idx, type_id, n = blocks[0]
    return type_id, n, read_block_floats(donor[HEADER:], idx, n)


def resolve_params(type_id: int, params: dict, where: str, donor: bytes) -> dict[int, float]:
    """{float index: value} for a chain entry's ``params``: a measured name through the plug-in's
    table (the donor's block length checked), or an index inside the donor's block."""
    _tid, n, floats = _block(donor)
    plugin = NAMES.get(type_id, f"type {type_id}")
    named = {k: v for k, v in params.items() if not str(k).lstrip("-").isdigit()}
    out: dict[int, float] = {}
    if named:
        if type_id not in PARAMS:
            raise ValueError(f"{where}: {plugin} has no measured parameter names; give float indices")
        try:
            set_params(type_id, floats, named)
        except ValueError as e:
            raise ValueError(f"{where}: {e}") from None
        out.update({PARAMS[type_id][k]: float(v) for k, v in named.items()})
    for k, v in params.items():
        if str(k).lstrip("-").isdigit():
            i = int(k)
            if not 0 <= i < n:
                raise ValueError(f"{where}: float index {i} is outside the {plugin} block of {n}")
            out[i] = float(v)
    return out


def plan_channels(data: bytes, config: dict, extra: dict, id_offsets) -> tuple[dict[int, list], set[str]]:
    """owner -> slots for every chain keyed by a channel name, and the names matched. A name two
    channels carry is refused; a name the project lacks is left to the report."""
    by_label = owners_by_label(data)
    plan: dict[int, list] = {}
    matched: set[str] = set()
    for name, spec in config["chains"].items():
        if name.endswith(".cst"):
            continue
        owners = by_label.get(CHANNEL_NAMES.get(name, name), [])
        if not owners:
            continue
        if len(owners) > 1:
            raise ValueError(f"{name}: {len(owners)} channels carry that label; rename one before keying a chain by it")
        (owner,) = owners
        label = f"{config.get('label_prefix', 'Trk')} - {spec.get('label', name)}"
        slots, key = [], slot_index_base(data)
        for entry in spec.get("plugins", []):
            donor = entry.get("donor")
            if donor not in extra:
                raise ValueError(f"{name}: donor {donor!r} is not declared under 'donors' or has no record")
            raw, tid = extra[donor]
            overrides = resolve_params(tid, entry.get("params") or {}, f"{name}: {donor}", raw)
            slots.append((raw, key, None, 0, label, id_offsets(data, tid, raw), tid, False, overrides))
            key += 1
        if slots:
            plan[owner] = slots
            matched.add(name)
    return plan, matched


def verify_channel_values(data: bytes, config: dict, extra: dict, id_offsets) -> list[str]:
    """Every configured parameter of a channel-keyed chain, read back from the WRITTEN project's
    slot at its key; a plug-in or a value that did not land is reported."""
    plan, _matched = plan_channels(data, config, extra, id_offsets)
    problems = []
    for owner, slots in plan.items():
        by_key = {}
        for r in project_records(data):
            if r.tag == b"UCuA" and r.owner == owner and b"GAMETSPP" in r.raw:
                tid, _n, floats = _block(r.raw)
                by_key[r.key] = (tid, floats)
        for _raw, key, _f, _l, _label, _ids, tid, _b, overrides in slots:
            name = f"{channel_name(data, owner)}: {NAMES.get(tid, tid)}"
            got = by_key.get(key)
            if got is None or got[0] != tid:
                problems.append(f"{name} is not at slot key {key}")
                continue
            off = [i for i, v in overrides.items()
                   if i >= len(got[1]) or abs(got[1][i] - v) > TOLERANCE * max(1.0, abs(v))]
            if off:
                problems.append(f"{name}: float(s) {off} did not take the configured value")
    return problems
