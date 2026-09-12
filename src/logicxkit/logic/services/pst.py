"""`.pst` authoring: one `GAMETSPP` chunk at offset 0, patched into Logic's own factory
`#default.pst`. Loading one touches only its plugin slot; loading a `.cst` replaces the whole
channel's routing."""

from __future__ import annotations

from pathlib import Path

from .._binary import find_blocks, patch_block_floats
from .library import factory_settings, logic_user_data, require_plain_names, resolve

# spec key -> (Logic's plugin folder name, GAMETSPP type id)
PLUGINS = {
    "eq": ("Channel EQ", 236),
    "comp": ("Compressor", 154),
    "limiter": ("Limiter", 199),
}


def factory_default(plugin_dir: str) -> Path:
    return factory_settings() / plugin_dir / "#default.pst"


def build_pst(template_bytes: bytes, values: list[float]) -> bytes:
    """Patch ``values`` into the template preset's chunk, clamped to what it holds."""
    blocks = find_blocks(template_bytes)
    if not blocks:
        raise ValueError("template is not a .pst: no GAMETSPP chunk")
    idx, _type_id, n = blocks[0]
    buf = bytearray(template_bytes)
    patch_block_floats(buf, idx, 0, values[:min(len(values), n)])
    return bytes(buf)


def _values_for(kind: str, preset: dict) -> list[float]:
    from .comp import build_comp
    from .eq import build_eq
    from .limiter import build_limiter
    return {"eq": build_eq, "comp": build_comp, "limiter": build_limiter}[kind](preset[kind])


def output_root(spec: dict) -> Path:
    """Where a spec's `.pst` files land; Logic's own user folder when it names no root."""
    return resolve(spec["output_dir"], spec.get("output_root") or logic_user_data())


def plan_psts(spec: dict) -> list[tuple[str, Path, list[float]]]:
    """[(name, destination path, float values)] for every plugin setting the spec defines."""
    require_plain_names(spec["presets"])
    out_root = output_root(spec)
    plan = []
    for name, preset in spec["presets"].items():
        for kind in PLUGINS:
            if kind in preset:
                folder, _type_id = PLUGINS[kind]
                plan.append((name, out_root / folder / f"{name}.pst", _values_for(kind, preset)))
    return plan


def write_psts(spec: dict, *, overwrite: bool = False):
    """Write each planned .pst from Logic's factory default. Yields (path, status)."""
    from pf_core.utils.io import atomic_write_bytes

    cache: dict[str, bytes] = {}
    for _name, dest, values in plan_psts(spec):
        if dest.exists() and not overwrite:
            yield dest, "skipped (exists)"
            continue
        folder = dest.parent.name
        if folder not in cache:
            src = factory_default(folder)
            if not src.exists():
                yield dest, f"FAILED (no factory default for {folder})"
                continue
            cache[folder] = src.read_bytes()
        dest.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(dest, build_pst(cache[folder], values))
        yield dest, "written"
