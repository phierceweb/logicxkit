"""`logic regions`'s edit specs: a listing number, ``N=VALUE`` pairs, switches and fades, each
refused with the shape it wants."""

from __future__ import annotations

from ._edit import CommandError
from .services.regions.fades import OUT_CODES


def _number(text: str, what: str) -> float:
    try:
        return float(text)
    except ValueError:
        raise CommandError(f"bad {what} {text!r}: a bar number, fractions allowed") from None


def _index(text: str, flag: str) -> int:
    if not text.isdigit() or int(text) < 1:
        raise CommandError(f"bad --{flag} {text!r}: N is a region's number in the listing")
    return int(text)


def _split(spec: str, flag: str, shape: str) -> tuple[int, str]:
    n, sep, rest = spec.partition("=")
    if not sep:
        raise CommandError(f"bad --{flag} {spec!r}: {shape}")
    return _index(n, flag), rest


def _switch(spec: str, flag: str) -> tuple[int, bool]:
    n, _sep, rest = spec.partition("=")
    if rest not in ("", "on", "off"):
        raise CommandError(f"bad --{flag} {spec!r}: N, N=on or N=off")
    return _index(n, flag), rest != "off"


def _fade(spec: str, flag: str) -> tuple[int, int | None, int, str]:
    """``N=MS[:CURVE[:TYPE]]`` -> (N, ms, curve, type); a crossfade's MS may be empty (the overlap)."""
    shape = {"fade-in": "N=MS[:CURVE[:speed-up]]", "fade-out": "N=MS[:CURVE[:out|x|eqp|xs]]", "crossfade": "N=[MS][:CURVE[:x|eqp|xs]]"}[flag]
    n, rest = _split(spec, flag, shape)
    parts = rest.split(":")
    try:
        ms = None if flag == "crossfade" and not parts[0] else int(parts[0])
        curve = int(parts[1]) if len(parts) > 1 and parts[1] else 0
    except ValueError:
        raise CommandError(f"bad --{flag} {spec!r}: {shape}") from None
    kind = parts[2] if len(parts) > 2 else ""
    kinds = {"fade-in": ("", "in", "speed-up"), "fade-out": ("", *OUT_CODES), "crossfade": ("", "x", "eqp", "xs")}[flag]
    if kind not in kinds or len(parts) > 3:
        raise CommandError(f"bad --{flag} {spec!r}: {shape}")
    return n, ms, curve, kind


def _int(spec: str, flag: str, shape: str) -> tuple[int, int]:
    n, rest = _split(spec, flag, shape)
    try:
        return n, int(rest)
    except ValueError:
        raise CommandError(f"bad --{flag} {spec!r}: {shape}") from None
