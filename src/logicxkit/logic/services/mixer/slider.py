"""One of Logic's own sliders as measured: the (units, value) points of its Controls-view row,
sampled position by position (`automation` in a native map's JSON). A written value goes where the
slider keeps it (`snap`): a linear row's unit, a knob row's nearer sampled position, or in a gap
between a knob row's samples the curve's value at the nearest unit. An automation point is
0..1 over the slider: Logic lays it on units floor(value x `per` + `offset`), clamped at the
slider's top — `per` 128 for most rows, the slider's span for a percentage, the Channel EQ's
gains affine — and the slider's own scale gives the value. Without a measured slider a lane is
reported, not guessed."""

from __future__ import annotations

import math
import struct
from itertools import pairwise

SWITCH_PER = 128.0                     # units per 1.0 for most of Logic's own parameters


def interp(points, x: float) -> float:
    """Piecewise-linear through monotonic ``points``, clamped to their ends."""
    pts = sorted(points)
    if x <= pts[0][0]:
        return pts[0][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:], strict=False):
        if x <= x1:
            return y0 if x1 == x0 else y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return pts[-1][1]


def along(curve, x: float, inverse: bool = False) -> float:
    """Units to value along a slider's (units, value) curve, or value to units; a curve spanning
    over twenty times, like a frequency's, is followed in the log domain."""
    logs = all(v > 0 for _u, v in curve) and curve[-1][1] / min(v for _u, v in curve) > 20
    if inverse:
        if logs and x <= 0:
            return curve[0][0]                                 # below any positive value: the bottom unit
        return interp(tuple((math.log2(v) if logs else v, u) for u, v in curve), math.log2(x) if logs else x)
    y = interp(tuple((u, math.log2(v) if logs else v) for u, v in curve), x)
    return 2 ** y if logs else y


def slider_curve(m, param: str):
    """The measured (units, value) points of one of Logic's own parameters, or None."""
    table = m.raw.get("automation", {}).get(param)
    return tuple((float(x), float(y)) for x, y in table["units"]) if table and table.get("units") else None


def ties_up(m, param: str) -> bool:
    """A row whose map says Logic lays a midpoint between two sampled positions on the upper one."""
    return m.raw.get("automation", {}).get(param, {}).get("tie") == "up"


def land(curve, param: str, value: float, up: bool = False) -> tuple[float, float]:
    """(unit, value) where a measured slider keeps ``value`` — the one decision every writer
    shares. Beyond the slider, its end. On a linear row, the unit `linear_unit` gives and that
    unit's value, sampled or not (every value Logic wrote on such a row sits on a whole unit, and
    eight values written between the samples came back on the predicted ones,
    `slider-linear-resave-logic`). On a knob-shaped row, the nearer of the two sampled positions
    around it; a value midway between them goes to the lower, or to the upper where ``up`` (the
    row's `tie` in its map). The taper decides there, not the two values: of sixteen rows measured
    at four midpoints each, six went up every time, six down and four either way
    (`slider-midpoints-resave-logic`, `slider-ties1..3-resave-logic`); the twenty-three rows sharing an
    up row's curve went up too (`slider-siblings-resave-logic`). On two more rows the map's samples
    are display-rounded (Noise Gate Release, the Multipressor's band 1 compression ratio), so a
    value midway between them is not the slider's midpoint.
    In a gap between a knob row's samples, the curve's value at the nearest unit along
    them (`knob_unit`: exact where the samples around it lie on a line, unmeasured otherwise)."""
    if not math.isfinite(value):
        raise ValueError(f"{param}: {value} is not a finite number")
    if any(b[1] < a[1] for a, b in pairwise(curve)):       # the neighbour search below assumes a rising row
        raise ValueError(f"{param}: its sampled values fall as the units rise; only a rising slider is landed")
    lo, hi = min(v for _u, v in curve), max(v for _u, v in curve)
    if lo == hi:                                                  # one point, or a row that never moves: its first point
        return curve[0][0], round(curve[0][1], 4)
    value = min(max(value, lo), hi)
    rounded = round(value, 4)                                     # a curve's 115.000009 means 115: no float noise decides a tie
    hit = next(((u, v) for u, v in curve if v == rounded), None)   # a plateau's first unit
    if hit is not None:
        return hit
    if is_linear(curve):
        (u0, v0), (u1, v1) = curve[0], curve[-1]
        unit = linear_unit(curve, value)                          # the slider's own arithmetic sees the value as given
        at = next((v for u, v in curve if u == unit), None)
        return unit, round(v0 + (v1 - v0) / (u1 - u0) * (unit - u0) if at is None else at, 4)
    below = max(((u, v) for u, v in curve if v < rounded), default=None)
    above = min(((u, v) for u, v in curve if v > rounded), default=None)
    if below and above and above[0] - below[0] == 1:          # both neighbours measured: the nearer value, a tie by the row
        down, upward = round(rounded - below[1], 6), round(above[1] - rounded, 6)
        picked = below if down < upward or (down == upward and not up) else above
        return min(u for u, v in curve if v == picked[1]), round(picked[1], 4)   # a plateau's first unit, as a hit
    unit = knob_unit(curve, rounded)                           # a gap in the samples: the curve's value at its nearest unit
    at = next((v for u, v in curve if u == unit), None)
    if at is not None:
        return min(u for u, v in curve if v == at), round(at, 4)       # a plateau's first unit, as a hit
    return unit, round(along(curve, unit), 4)


def snap(m, param: str, value: float) -> float:
    """``value`` where the slider keeps it (`land`); as given where the map does not measure the row."""
    curve = slider_curve(m, param)
    if curve is None:
        if not math.isfinite(value):
            raise ValueError(f"{param}: {value} is not a finite number")
        return value
    return land(curve, param, value, ties_up(m, param))[1]


def knob_unit(curve, value: float) -> float:
    """The unit a knob-shaped row's ``value`` is nearest along the sampled curve, a half going down
    as a measured midpoint between two sampled positions does; within the slider."""
    unit = math.ceil(along(curve, value, inverse=True) - 0.5)
    return float(max(curve[0][0], min(curve[-1][0], unit)))


def _f32(x: float) -> float:
    return struct.unpack("f", struct.pack("f", x))[0]


def linear_unit(curve, value: float) -> float:
    """The unit a linear row's slider lands ``value`` on: Logic's own arithmetic in single
    precision — (value - bottom) / step, rounded half up — within the slider. It decides every
    measured midpoint: six on four plug-ins (`snap-raw-resave-logic`, `slider-snap-raw-resave-logic`:
    a Noise Gate hold 205 as 210, a Linear Phase EQ gain 1.55 as 1.5, a Limiter output level -0.15 as
    -0.1) and eight between a row's samples (`slider-linear-resave-logic`: a Compressor knee 0.85 as 0.9)."""
    (u0, v0), (u1, v1) = curve[0], curve[-1]
    step = _f32((v1 - v0) / (u1 - u0))
    unit = math.floor(_f32(_f32(_f32(value) - v0) / step) + 0.5) + u0
    return float(max(u0, min(u1, unit)))


def grid_value(m, param: str, value: float) -> tuple[float, tuple[float, float] | None]:
    """``value`` as the slider keeps it — held to the measured ends, then where `snap` lands it — with
    the slider's ends when the value lay outside them. A parameter the map does not measure takes the
    vocabulary item's step where it has one, else comes back as given."""
    if not math.isfinite(value):
        raise ValueError(f"{param}: {value} is not a finite number")
    curve = slider_curve(m, param)
    if curve:                                             # the slider decides: its units are the item's steps or finer
        return land(curve, param, value, ties_up(m, param))[1], past_ends(curve, value)
    item = next((i for i in m.items.values() if i.param.lower() == param.lower()), None)
    if item is not None and item.step and not item.switch:
        value = round(round(value / item.step) * item.step, 6)
    return value, None


def units_at(value: float, per: float, offset: float, top: float) -> float:
    """The slider units Logic lays a point on: floor(value x per + offset), within the slider."""
    return max(0.0, min(math.floor(value * per + offset + 1e-9), top))


def point_at(units: float, per: float, offset: float = 0.0) -> float:
    """The 0..1 that lands on ``units``: the middle of the unit, so no rounding tips it down
    (a value a hair under a unit, from a point's own quantization, counts as that unit)."""
    return min(1.0, max(0.0, (math.floor(units + 1e-4) + 0.5 - offset) / per))


def point_for(m, param: str, value: float | bool) -> tuple[float, float, float, bool]:
    """A native parameter's own value as its 0..1 point: (point, the slider unit it lands on,
    that unit's value, whether the table sampled that unit — else the value is interpolated).
    A switch is 1.0 or 0.0."""
    if isinstance(value, bool):
        return (1.0 if value else 0.0), (1.0 if value else 0.0), (1.0 if value else 0.0), True
    per, offset, curve = slider_by_name(m, param)
    units, landed = land(curve, param, value, ties_up(m, param))
    return point_at(units, per, offset), units, landed, is_linear(curve) or any(u == units for u, _v in curve)


def past_ends(curve, value: float) -> tuple[float, float] | None:
    """The slider's ends when ``value`` lies past them as `land` sees it (to four places), else None;
    a NaN reads as past them, so callers refuse it first."""
    lo, hi = min(v for _u, v in curve), max(v for _u, v in curve)
    return None if lo <= round(value, 4) <= hi else (lo, hi)


def is_linear(curve) -> bool:
    """A row whose sampled values run at one step per unit (the dB rows): a value between two
    samples is exact, not a guess — every value Logic wrote on one sits on a whole unit of its line
    (`tests/goldens/test_translate_snap.py`)."""
    (u0, v0), (u1, v1) = curve[0], curve[-1]
    if u1 == u0:
        return True
    step = (v1 - v0) / (u1 - u0)
    return all(abs(v - (v0 + step * (u - u0))) <= 1e-6 * max(1.0, abs(v)) for u, v in curve)


def slider_by_name(m, param: str | None) -> tuple[float, float, tuple[tuple[float, float], ...]]:
    """(units per 1.0 of automation, the offset, the slider's (units, value) points)."""
    table = m.raw.get("automation", {}).get(param or "")
    if not table or not table.get("units"):
        raise ValueError(f"{m.plugin} {param}: its slider is not measured for automation; the lane cannot be carried")
    return (float(table.get("per", SWITCH_PER)), float(table.get("offset", 0.0)),
            tuple((float(x), float(y)) for x, y in table["units"]))
