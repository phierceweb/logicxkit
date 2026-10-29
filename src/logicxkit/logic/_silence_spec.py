"""A strip-silence spec: ``{"groups": [{"tracks": [...], <setting>: ...}, ...]}``, each group's
settings named as the command's flags with underscores, read into one `Settings` per group; the
parsers and refusals the command's own flags go through."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, fields
from pathlib import Path

from .orchestrators.strip_silence import Settings

KEYS = ("threshold", "edge", "min_gap", "min_keep", "pad", "fade", "ref", "band", "above", "gate", "window",
        "against_band", "tilt_band", "tilt")
IGNORED = ("_", "_comment")
LONGEST_S, LONGEST_MS = 86_400, 3_600_000      # a day of gap or keep, an hour of pad or window: past these a figure is a typo
DB_SPAN = 200                                   # no level or margin in dB is further from 0 than this
FADE_LIMIT = 0xFFFF                             # the fade writer's two bytes


@dataclass(frozen=True)
class Group:
    tracks: tuple[str, ...]
    settings: Settings


def band(value) -> tuple[int, int]:
    """``LOW:HIGH`` in Hz (a string), or ``[low, high]``."""
    complaint = f"{value}: a band is LOW:HIGH in whole Hz, 0 < LOW < HIGH"
    if isinstance(value, (list, tuple)) and len(value) == 2:
        low, high = value
    else:
        low, sep, high = str(value).partition(":")
        if not sep:
            raise ValueError(complaint)
    lo, hi = _whole(low, complaint), _whole(high, complaint)
    if not 0 < lo < hi:
        raise ValueError(complaint)
    return lo, hi


def pad(value) -> tuple[int, int]:
    """``MS``, ``BEFORE:AFTER`` or ``[before, after]`` in whole ms."""
    if isinstance(value, (list, tuple)) and len(value) == 2:
        before, after = value
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        before = after = value
    else:
        before, sep, after = str(value).partition(":")
        after = after if sep else before
    complaint = f"{value}: a pad is MS, or BEFORE:AFTER in whole ms, 0 to {LONGEST_MS}"
    lo, hi = _whole(before, complaint), _whole(after, complaint)
    if not 0 <= lo <= LONGEST_MS or not 0 <= hi <= LONGEST_MS:
        raise ValueError(complaint)
    return lo, hi


def _whole(value, complaint: str) -> int:
    """``value`` as a whole number; a fraction, a word, a bool or a non-finite is refused."""
    if isinstance(value, bool):
        raise ValueError(complaint)
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(complaint) from None
    if not math.isfinite(number) or number != int(number):
        raise ValueError(complaint)
    return int(number)


def _number(value, what: str, *, at_most: float | None = None, above: float | None = None, at_least: float | None = None) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{what} {value!r}: a number")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{what} {value!r}: a number") from None
    if not math.isfinite(number):
        raise ValueError(f"{what} {value!r}: a number")
    if at_most is not None and number > at_most:
        raise ValueError(f"{what} {value}: {at_most:g} or below")
    if above is not None and number <= above:
        raise ValueError(f"{what} {value}: above {above:g}")
    if at_least is not None and number < at_least:
        raise ValueError(f"{what} {value}: {at_least:g} or more")
    return number


def settings_from(given: dict) -> Settings:
    """A `Settings` from the keys given (`KEYS`, the flags' names with underscores), the rest
    the defaults, refused as the command refuses them."""
    unknown = [k for k in given if k not in KEYS and k not in IGNORED]
    if unknown:
        raise ValueError(f"unknown setting {unknown[0]!r}; the settings are " + ", ".join(KEYS))
    g = {k: v for k, v in given.items() if k in KEYS and v is not None}
    refs = tuple(g["ref"]) if isinstance(g.get("ref"), (list, tuple)) else ((g["ref"],) if "ref" in g else ())
    if not all(isinstance(ref, str) and ref for ref in refs):
        raise ValueError("ref names tracks: a name, or a list of names")
    if len(set(refs)) != len(refs):
        twice = next(ref for ref in refs if refs.count(ref) > 1)
        raise ValueError(f"ref {twice!r} is named twice")
    for key in ("above", "gate", "window", "against_band"):
        if key in g and not refs:
            raise ValueError(f"{key} is the bleed rule's; it needs ref")
    for key in ("tilt", "tilt_band"):
        if key in g and "against_band" not in g:
            raise ValueError(f"{key} needs against_band")
    s = Settings()
    threshold = _number(g["threshold"], "threshold", at_most=0, at_least=-DB_SPAN) if "threshold" in g else s.threshold_db
    edge = _number(g["edge"], "edge", at_most=0, at_least=-DB_SPAN) if "edge" in g else max(s.edge_db, threshold)
    if edge < threshold:
        raise ValueError(f"edge {edge:g} is further under the loud level than threshold {threshold:g}; the edge limit crops a "
                         "gap's edges, so it sits at or above the gap limit")
    tilt_band = g.get("tilt_band")
    if tilt_band is not None and str(tilt_band).strip().lower() != "auto":
        tilt_band = band(tilt_band)
    elif tilt_band is not None:
        tilt_band = "auto"
    return Settings(
        threshold_db=threshold, edge_db=edge,
        min_gap_s=_number(g["min_gap"], "min_gap", at_least=0, at_most=LONGEST_S) if "min_gap" in g else s.min_gap_s,
        min_keep_s=_number(g["min_keep"], "min_keep", at_least=0, at_most=LONGEST_S) if "min_keep" in g else s.min_keep_s,
        pad_ms=pad(g["pad"]) if "pad" in g else s.pad_ms,
        fade_ms=_ms(g, "fade", FADE_LIMIT, s.fade_ms),
        band=band(g["band"]) if "band" in g else None,
        refs=refs,
        above_db=_number(g["above"], "above", above=0, at_most=DB_SPAN) if "above" in g else s.above_db,
        gate_db=_number(g["gate"], "gate", at_least=0, at_most=DB_SPAN) if "gate" in g else None,
        window_ms=_ms(g, "window", LONGEST_MS, s.window_ms),
        against=band(g["against_band"]) if "against_band" in g else None,
        tilt_db=_number(g["tilt"], "tilt", at_least=-DB_SPAN, at_most=DB_SPAN) if "tilt" in g else s.tilt_db,
        tilt_band=tilt_band,
    )


def _ms(g: dict, key: str, limit: int, default: int) -> int:
    if key not in g:
        return default
    complaint = f"{key} {g[key]!r}: whole ms, 0 to {limit}"
    value = _whole(g[key], complaint)
    if not 0 <= value <= limit:
        raise ValueError(complaint)
    return value


def read_spec(path: Path) -> list[Group]:
    try:
        spec = json.loads(Path(path).read_text())
    except (OSError, ValueError) as e:
        raise ValueError(f"{path}: {e}") from None
    groups = spec.get("groups") if isinstance(spec, dict) else None
    if not isinstance(groups, list) or not groups:
        raise ValueError(f"{path}: a spec is {{\"groups\": [{{\"tracks\": [...], ...}}, ...]}}")
    stray = [k for k in spec if k != "groups" and k not in IGNORED]
    if stray:
        raise ValueError(f"{path}: {stray[0]!r} at the top level; the settings go inside a group")
    seen: dict[str, int] = {}
    out = []
    for k, group in enumerate(groups, 1):
        if not isinstance(group, dict) or not isinstance(group.get("tracks"), list) or not group["tracks"] \
                or not all(isinstance(t, str) and t for t in group["tracks"]):
            raise ValueError(f"{path}: group {k} needs \"tracks\", a list of track names")
        for track in group["tracks"]:
            if seen.get(track) == k:
                raise ValueError(f"{path}: {track!r} is named twice in group {k}")
            if track in seen:
                raise ValueError(f"{path}: {track!r} is in two groups ({seen[track]} and {k})")
            seen[track] = k
        try:
            settings = settings_from({kk: v for kk, v in group.items() if kk != "tracks"})
        except ValueError as e:
            raise ValueError(f"{path}: group {k}: {e}") from None
        for track in group["tracks"]:
            if track in settings.refs:
                raise ValueError(f"{path}: group {k}: {track!r} is both cut and a reference")
        out.append(Group(tuple(group["tracks"]), settings))
    return out


SETTINGS_FIELDS = tuple(f.name for f in fields(Settings))
