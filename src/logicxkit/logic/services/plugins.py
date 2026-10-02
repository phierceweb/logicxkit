"""Which plug-ins a project references, and whether this Mac has them.

A native slot carries Logic's `GAMETSPP` block with the plug-in's type id (`_binary.find_blocks`);
a third-party slot embeds an AU preset plist whose `type`, `subtype` and `manufacturer` are the
component identity (`au.services.embed`). The installed set is what `auval -a` lists — a
registry that keeps a component whose bundle has gone bad, as Logic's own launch does, so
``validate_components`` opens each one with `auval -v` when asked. Apple's own components are
counted present without asking: Logic ships them.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, replace

from ...au.services.aupreset import parse_au_state
from ...au.services.embed import find_au_plists
from .._binary import find_blocks
from .binding import channels
from .plugin_names import NATIVE_INSTRUMENTS, PLUGIN_VARIANTS, native_name
from .slot_width import plugin_variant
from .stream import HEADER, project_records
from .plugin_names import plugin_name
from .sends import is_send
from .sidechain import side_chain, source_name

APPLE = "appl"
_AUVAL_LINE = re.compile(r"^(.{4}) (.{4}) (.{4})\s+-\s+")


@dataclass(frozen=True)
class PluginRef:
    channel: str
    key: int
    name: str
    native: bool
    component: tuple[str, str, str] | None     # (type, subtype, manufacturer) of a third-party AU
    side_chain: str | None = None              # what the project calls the slot's side-chain source


@dataclass(frozen=True)
class Verdict:
    slots: list[tuple[PluginRef, str]]        # status: apple, installed, missing, broken, unknown
    missing: list[PluginRef]

    @property
    def clean(self) -> bool:
        return not self.missing


def _ref(label: str, key: int, payload: bytes) -> PluginRef | None:
    blocks = find_blocks(payload)
    if blocks:
        type_id = blocks[0][1]
        return PluginRef(label, key, plugin_name(payload) or native_name(type_id, plugin_variant(payload)) or f"type {type_id}", True, None)
    for _off, plist in find_au_plists(payload):
        if "manufacturer" not in plist:
            continue
        st = parse_au_state(plist)
        return PluginRef(label, key, f"{st.manufacturer}/{st.subtype}", st.manufacturer == APPLE,
                         (st.type, st.subtype, st.manufacturer))
    return None


def plugin_identity(payload: bytes) -> tuple | None:
    """``("native", type_id)`` — ``("native", type_id, variant)`` where the type is shared
    (`PLUGIN_VARIANTS`) — or ``("au", type, subtype, manufacturer)`` for a slot payload."""
    blocks = find_blocks(payload)
    if blocks:
        type_id = blocks[0][1]
        return ("native", type_id, plugin_variant(payload)) if type_id in PLUGIN_VARIANTS else ("native", type_id)
    ref = _ref("", 0, payload)
    return ("au", *ref.component) if ref is not None and ref.component else None


def is_instrument_plugin(payload: bytes) -> bool:
    """An instrument or generator — what an instrument channel's slot 1 holds."""
    identity = plugin_identity(payload)
    if identity is None:
        return False
    return identity[1] in NATIVE_INSTRUMENTS if identity[0] == "native" else identity[1] in ("aumu", "augn")


def slot_payloads(data: bytes) -> list[tuple[PluginRef, bytes]]:
    """Every plug-in slot in record order, with its channel's label and its payload."""
    labels = {o: c.label for o, c in channels(data).items()}
    out = []
    for r in project_records(data):
        if r.tag != b"UCuA" or r.owner not in labels or is_send(r):
            continue
        payload = r.raw[HEADER:]
        ref = _ref(labels[r.owner], r.key, payload)
        if ref is not None:
            sc = side_chain(payload)
            out.append((replace(ref, side_chain=source_name(data, sc)) if sc else ref, payload))
    return out


def project_plugins(data: bytes) -> list[PluginRef]:
    """Every plug-in slot in record order, with its channel's label."""
    return [ref for ref, _payload in slot_payloads(data)]


def installed_from_auval(text: str) -> set[tuple[str, str, str]]:
    out = set()
    for line in text.splitlines():
        m = _AUVAL_LINE.match(line)
        if m:
            out.add((m.group(1), m.group(2), m.group(3)))
    return out


REGISTRY_TIMEOUT = 300               # one `auval -a` over the whole registry


def installed_components(*, timeout: float = REGISTRY_TIMEOUT) -> set[tuple[str, str, str]] | None:
    """What `auval -a` lists, or None when the tool is not on this machine or its registry scan
    ran past ``timeout`` — either way the third-party status is unknown, not clean."""
    auval = shutil.which("auval")
    if auval is None:
        return None
    try:
        run = subprocess.run([auval, "-a"], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None
    return installed_from_auval(run.stdout)


VALIDATE_TIMEOUT = 300               # per component; a hang past it reads as broken
FAILED_MARKERS = ("FATAL ERROR", "AU VALIDATION FAILED", "* * FAIL")
PASSED_MARKERS = ("AU VALIDATION SUCCEEDED", "* * PASS")


def validate_components(components: set[tuple[str, str, str]], *, timeout: float = VALIDATE_TIMEOUT,
                        progress=None) -> dict[tuple[str, str, str], bool]:
    """Whether each component opens and passes `auval -v` — the check the registry cannot make.
    A component that hangs past ``timeout`` is broken; ``progress(component)`` is called before
    each one. Empty without `auval`, which `verdict` reads as nothing checked."""
    auval = shutil.which("auval")
    if auval is None:
        return {}
    out = {}
    for comp in sorted(components):
        if progress is not None:
            progress(comp)
        try:
            run = subprocess.run([auval, "-v", *comp], capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            out[comp] = False
            continue
        text = run.stdout + run.stderr
        out[comp] = (run.returncode == 0 and any(m in text for m in PASSED_MARKERS)
                     and not any(m in text for m in FAILED_MARKERS))
    return out


def verdict(refs: list[PluginRef], installed: set[tuple[str, str, str]] | None,
            validated: dict[tuple[str, str, str], bool] | None = None) -> Verdict:
    """``validated`` (from `validate_components`) marks a listed component that fails to open as
    broken, which counts as missing."""
    slots, missing = [], []
    for ref in refs:
        if ref.native:
            status = "apple"
        elif installed is None:
            status = "unknown"
        elif ref.component in installed:
            status = "installed"
            if validated is not None and validated.get(ref.component) is False:
                status = "broken"
                missing.append(ref)
        else:
            status = "missing"
            missing.append(ref)
        slots.append((ref, status))
    return Verdict(slots, missing)
