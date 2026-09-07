"""Spec loading + strip assembly — turn a JSON spec + template .cst into patched bytes.

Template-based by necessity: the proprietary `.cst` header and plugin-slot table are not
synthesised. We clone a template that already has the plugin chain, then rewrite the first
Channel EQ and first Compressor `GAMETSPP` blocks from the spec.
"""

from __future__ import annotations

import json
from pathlib import Path

from .._binary import find_blocks, identify_plugin, patch_block_floats, read_block_floats
from .comp import build_comp, decode_comp
from .eq import build_eq, decode_eq
from .library import resolve
from .limiter import build_limiter
from .graft import graft, relabel_presets, set_provenance
from .records import plugin_slots, replace_slots


def _patch_group(buf: bytearray, blocks, plugin: str, vals: list[float], limit: int) -> bool:
    """Patch the first ``plugin`` block AND its Logic-re-save paired copies.

    A re-saved strip writes each slot as two consecutive same-size GAMETSPP blocks; the
    copy reads as ``Unknown`` (its plugin-name label is outside identify_plugin's window).
    We patch the identified block, then every immediately-following block of identical
    float count that identifies as the same plugin or ``Unknown`` — writing only the
    user-param region (``limit`` floats), so each copy's trailing internal floats survive.
    Returns True if at least one block was patched.
    """
    for i, (idx, _size, n) in enumerate(blocks):
        if identify_plugin(bytes(buf), idx) != plugin:
            continue
        patch_block_floats(buf, idx, 0, vals[:min(limit, n)])
        for jdx, _js, jn in blocks[i + 1:]:
            if jn != n or identify_plugin(bytes(buf), jdx) not in (plugin, "Unknown"):
                break
            patch_block_floats(buf, jdx, 0, vals[:min(limit, jn)])
        return True
    return False


def build_strip(template_bytes: bytes, preset: dict) -> bytes:
    """Clone template and patch its Channel EQ and Compressor blocks (all paired copies)."""
    buf = bytearray(template_bytes)
    blocks = find_blocks(bytes(buf))

    for key, plugin, build, limit in (("eq", "Channel EQ", build_eq, 33),
                                      ("comp", "Compressor", build_comp, 14),
                                      ("limiter", "Limiter", build_limiter, 13)):
        if key in preset and not _patch_group(buf, blocks, plugin, build(preset[key]), limit):
            raise RuntimeError(f"template has no {plugin} block to patch")
    return bytes(buf)


def decode_strip(data: bytes) -> dict:
    """First Channel EQ + Compressor blocks -> a ``{eq?, comp?}`` spec fragment."""
    out: dict = {}
    for idx, _size, n in find_blocks(data):
        plugin = identify_plugin(data, idx)
        if plugin == "Channel EQ" and "eq" not in out and n >= 33:
            out["eq"] = decode_eq(read_block_floats(data, idx, 33))
        elif plugin == "Compressor" and "comp" not in out and n >= 14:
            out["comp"] = decode_comp(read_block_floats(data, idx, 14))
    return out


def template_path_for(spec: dict, preset: dict) -> Path:
    """Resolve a preset's template: per-preset ``template`` overrides the global default."""
    raw = preset.get("template", spec.get("template"))
    if raw is None:
        raise ValueError("preset has no 'template' and spec has no global 'template'")
    return resolve(raw, spec.get("strip_root"))


def resolve_base(spec: dict, preset: dict, load) -> bytes:
    """Base bytes for a preset: a whole ``template`` strip, or a ``graft`` of two.

    ``graft`` = {"routing_from": <strip whose routing/identity to keep>,
                 "chain_from":   <strip whose plugin chain to take>} — for chain shapes no
    single saved strip has.
    """
    root = spec.get("strip_root")
    reslot = preset.get("reslot")
    if reslot is not None:
        if "template" in preset or "graft" in preset:
            raise ValueError("preset sets 'reslot' with 'template'/'graft' — ambiguous base")
        target = load(resolve(reslot["routing_from"], root))
        if "keep_slots" in reslot:
            own = plugin_slots(target)
            chosen = [own[i].raw for i in reslot["keep_slots"] if i < len(own)]
        elif reslot.get("chain_from"):
            chosen = [r.raw for r in plugin_slots(load(resolve(reslot["chain_from"], root)))]
        else:
            chosen = []
        return replace_slots(target, chosen)

    spliced = preset.get("graft")
    if spliced is None:
        return load(template_path_for(spec, preset))
    if "template" in preset:
        raise ValueError("preset sets both 'template' and 'graft' — ambiguous base")
    missing = [k for k in ("routing_from", "chain_from") if k not in spliced]
    if missing:
        raise ValueError(f"graft missing {missing}")
    return graft(load(resolve(spliced["routing_from"], root)),
                 load(resolve(spliced["chain_from"], root)))


def assemble(spec: dict, preset: dict, load, name: str | None = None) -> bytes:
    """Full pipeline for one preset: base -> patch EQ/Comp -> ``label`` -> self-identity.

    ``name`` re-stamps the strip's own provenance record; without it a clone or graft keeps
    claiming to be its donor.
    """
    data = build_strip(resolve_base(spec, preset, load), preset)
    if "label" in preset:
        data = relabel_presets(data, preset["label"])
    if name:
        out_dir = spec.get("_output_dir")
        data = set_provenance(data, f"{name}.cst", Path(out_dir).name if out_dir else "")
    return data


def load_spec(spec_path: Path) -> dict:
    """Load + validate a JSON spec; resolve template/output paths (``_`` keys added)."""
    spec = json.loads(spec_path.read_text())
    for key in ("output_dir", "presets"):
        if key not in spec:
            raise ValueError(f"spec missing required key '{key}'")
    if "template" in spec:
        spec["_template_path"] = resolve(spec["template"], spec.get("strip_root"))
    # `strip_root` moves sources as well as output; `output_root` moves output only.
    spec["_output_dir"] = resolve(spec["output_dir"],
                                  spec.get("output_root") or spec.get("strip_root"))
    return spec
