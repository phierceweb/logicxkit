"""Headless AU introspection via the vendored Swift probe (``logicxkit/native/auprobe.swift``).

The probe instantiates an installed Audio Unit, optionally restores a preset /
ClassInfo plist (kAudioUnitProperty_ClassInfo), and prints one JSON document:
component identity plus every parameter with name, unit, min/max/default,
current value, and the UI-formatted display string
(kAudioUnitProperty_ParameterStringFromValue). This wrapper shells out and
parses; everything degrades to the static decoders when Swift or the AU is
absent.

Some AUs crash when instantiated without a UI host — denylisted from batch
decodes via :func:`is_headless_safe` (Waves state decodes statically in
``waves.py`` instead; sonible state is a protobuf ``jucePluginState``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from logicxkit.utils.swiftrun import SwiftRunError, native_dir, run_swift, swift_available

# Observed crashes: sonible (dyld abort), Waves (WaveShell objc class collision).
_HEADLESS_UNSAFE = {"Soni", "ksWV"}
_TIMEOUT_S = 120


class AuHostError(RuntimeError):
    """The probe failed: missing toolchain/component, crash, or bad output."""


def is_headless_safe(manufacturer_cc: str) -> bool:
    return manufacturer_cc not in _HEADLESS_UNSAFE


def auprobe_path() -> Path:
    return native_dir() / "auprobe.swift"


@dataclass(frozen=True)
class AuParam:
    id: int
    name: str
    unit: str
    min: float
    max: float
    default: float
    value: float | None = None
    display: str | None = None


@dataclass(frozen=True)
class AuDump:
    component: str
    type: str
    subtype: str
    manufacturer: str
    params: tuple[AuParam, ...]

    def changed_params(self, eps: float = 1e-6) -> list[AuParam]:
        return [p for p in self.params
                if p.value is not None and abs(p.value - p.default) > eps]


def _default_runner(args: list[str], timeout: float) -> tuple[int, str, str]:
    try:
        return run_swift(Path(args[0]), list(args[1:]), timeout)
    except SwiftRunError as e:
        raise AuHostError(str(e)) from e


class AuHost:
    def __init__(self, runner=None, timeout: float = _TIMEOUT_S):
        self._runner = runner or _default_runner
        self._timeout = timeout

    @staticmethod
    def available() -> bool:
        return swift_available() and auprobe_path().exists()

    def dump_preset(self, plist_path: str | Path) -> AuDump:
        """Instantiate the AU named inside the plist, restore it, dump values."""
        return self._invoke(["preset", str(plist_path)])

    def list_params(self, type_cc: str, subtype_cc: str, manu_cc: str) -> AuDump:
        """Parameter table (names/units/ranges/defaults) without preset state."""
        return self._invoke(["list", type_cc, subtype_cc, manu_cc])

    def _invoke(self, args: list[str]) -> AuDump:
        rc, out, err = self._runner([str(auprobe_path()), *args], self._timeout)
        if rc != 0:
            tail = (err or out).strip().splitlines()
            raise AuHostError(tail[-1] if tail else f"probe exited {rc}")
        start = out.find("{")
        if start < 0:
            raise AuHostError(f"unparseable probe output: {out[:120]!r}")
        try:
            d = json.loads(out[start:])
        except json.JSONDecodeError as e:
            raise AuHostError(f"bad probe JSON: {e}") from e
        params = tuple(
            AuParam(id=p["id"], name=p["name"], unit=p["unit"], min=p["min"],
                    max=p["max"], default=p["default"],
                    value=p.get("value"), display=p.get("display"))
            for p in d["params"])
        return AuDump(component=d["component"], type=d["type"], subtype=d["subtype"],
                      manufacturer=d["manufacturer"], params=params)
