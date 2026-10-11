"""What a written chain is checked against afterwards, each read back from the WRITTEN project:
every strip-sourced float against its strip, every channel-keyed value against the config, and a
superseded copy of a chain-placed plug-in left at a higher slot key."""

from __future__ import annotations

from .chain_donors import id_offsets_for, strip_params, strip_path
from .chains import channel_references
from .chains_channels import channel_name


def verify_strip_values(data: bytes, config: dict) -> list[str]:
    """Every strip-sourced float in a WRITTEN project, checked against the strip it came from:
    the build's own counts passing is not evidence the values landed."""
    from ..._binary import find_blocks, read_block_floats
    from ..stream.stream import project_records

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


def duplicate_chain_slots(data: bytes, plan: dict) -> list[tuple[int, int, int]]:
    """``(owner, slot key, plugin type id)`` for chain-placed plug-ins left twice on a channel: the
    plan writes from the first slot key up, so a channel whose own chain sat at higher keys keeps
    those records, and a survivor of a type the chain places is a superseded copy in series."""
    from ..._binary import find_blocks
    from ..stream.stream import project_records

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
    return [f"{refs.get(owner) or channel_name(data, owner)}: plugin {type_id} also survives at slot key "
            f"{key} — superseded copy of one the chain places" for owner, key, type_id in dupes]


def verify_channel_values(data: bytes, config: dict, extra: dict) -> list[str]:
    """The channel-keyed chains' parameters read back from a WRITTEN project (`chains_channels`)."""
    from .chains_channels import verify_channel_values as _verify

    return _verify(data, config, extra, id_offsets_for)
