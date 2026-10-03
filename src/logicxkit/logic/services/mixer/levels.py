"""Channel fader and pan — read them, and copy them between projects.

Both live in the `OCuA` channel record:

    +116..119      fader as u32, 8.24 fixed point: the integer part is the 0-127 position
    +85 and +119   the integer part again, twice (+119 is the u32's own high byte); all three
                   must agree, and do on every record measured
    +89            pan, 0-127, where 64 is centre.

Confirmed against Logic's own mixer display: pan reads out as ``byte - 64`` (-64 hard left,
+63 hard right), matching every hard-panned pair in the sessions, and fader byte 90 shows
0.0 dB. The taper is ``dB = 40 * log10(position / 90)``, position 0 being -∞ and 127 the top
(5.98, shown as 6.0): four fader positions Logic 12.4 saved showed -16.6, -5.3, 2.7 and 6.0 dB,
and 265 stops of its send knob, which stores the same word, fit it too. Logic shows a send's level rounded
down to the tenth, and the knob's own stops sit about 200 units above each mark (0 dB saved as
90 + 256 units): a send written on the mark itself read 0.1 dB low (-10.1 for -10.0), and
`level_word` writes it above. The fader's readout works on its own 234 steps instead, whose
values are the law's (-5.3, -6.4) except where a step sits between marks: the step it labels
-6.0 stores -5.98 dB, and an exact -6.0 dB, kept as written, reads -6.1 there.
"""

from __future__ import annotations

import math
import struct

from .mixer import CHANNEL_TAG
from ..stream.stream import HEADER, NO_KEY, project_records, reassemble
from ..stream.validate import require_full_walk, require_valid

FADER_AT = (85, 119)
FADER_FIXED_AT = 116
FIXED_ONE = 1 << 24
PAN_AT = 89
PAN_CENTRE = 64
UNITY = 90
_MIN_PAYLOAD = 200
TOP, TOP_DB = 127.0, 6.0
MARK_MARGIN = 256                 # units above a level's mark, as Logic's own 0 dB carries


def position_db(position: float) -> float | None:
    """The dB Logic shows for a fader or send position; ``None`` is -∞ (position 0)."""
    return 40 * math.log10(position / UNITY) if position > 0 else None


def db_position(db: float) -> float:
    """The position for ``db``: -inf is 0, and the top position stands for anything from its
    own 5.98 dB to the 6.0 Logic shows there."""
    if db == float("-inf"):
        return 0.0
    if math.isnan(db):
        raise ValueError("a level is a number of dB, or -inf")
    if db > TOP_DB:
        raise ValueError(f"a level is at most {TOP_DB} dB")
    return min(UNITY * 10 ** (db / 40), TOP)


def level_word(db: float) -> int:
    """The 8.24 word of a send at ``db``, just above its mark so Logic's knob shows that value."""
    position = db_position(db)
    if position == 0:
        return 0
    return min(round(position * FIXED_ONE) + MARK_MARGIN, int(TOP) * FIXED_ONE)


def db_text(db: float | None) -> str:
    """A level to the hundredth, as written; ``None`` is -∞."""
    return "-∞" if db is None else f"{db + 0.0:.2f}"


def fader_word(db: float) -> int:
    """The 8.24 word of a fader at ``db``: the law's own value, as Logic's fader steps store."""
    return int(db_position(db) * FIXED_ONE)


def shown_db(position: float) -> str:
    """A send level as Logic's knob shows it: rounded down to the tenth, the top as 6.0. The
    fader shows its own steps so, but not a level between them (an exact -6.0 shows -6.1)."""
    if position <= 0:
        return "-∞"
    if position >= TOP:
        return f"{TOP_DB:.1f}"
    return f"{math.floor(position_db(position) * 10 + 1e-6) / 10:.1f}"


def _is_mixer_channel(record) -> bool:
    return (record.tag == CHANNEL_TAG and record.key == NO_KEY
            and len(record.raw) - HEADER > _MIN_PAYLOAD)


def read_levels(data: bytes) -> dict[int, dict[str, int]]:
    """owner -> ``{"fader": 0-127, "pan": 0-127, "pan_display": -64..+63}``.

    A channel can own several records; the longest wins, the same rule ``channel_formats``
    uses, because the short ones are stubs that carry no mixer state.
    """
    best: dict[int, bytes] = {}
    for record in project_records(data):
        if not _is_mixer_channel(record):
            continue
        payload = record.raw[HEADER:]
        if record.owner not in best or len(payload) > len(best[record.owner]):
            best[record.owner] = payload
    out = {}
    for owner, payload in best.items():
        fixed = struct.unpack_from("<I", payload, FADER_FIXED_AT)[0]
        out[owner] = {"fader": payload[FADER_AT[0]], "fader_fixed": fixed,
                      "fader_exact": fixed / FIXED_ONE, "fader_db": position_db(fixed / FIXED_ONE),
                      "pan": payload[PAN_AT], "pan_display": payload[PAN_AT] - PAN_CENTRE}
    return out


def set_levels(data: bytes, want: dict[int, dict[str, int]]) -> tuple[bytes, list[int]]:
    """Write fader/pan onto channels -> ``(project, [owners changed])``.

    ``fader`` is the 0-127 position (fraction cleared); ``fader_fixed`` the exact 8.24 value
    and wins when both are given. Every record a changed owner has is rewritten, not just the
    longest: Logic keeps the mixer state in each copy, and leaving a stale one behind is how a
    fader springs back.
    """
    require_full_walk(data)
    changed: list[int] = []
    out = []
    for record in project_records(data):
        raw = record.raw
        spec = want.get(record.owner)
        if spec and _is_mixer_channel(record):
            buf = bytearray(raw)
            before = bytes(buf)
            fixed = spec.get("fader_fixed")
            if fixed is None and "fader" in spec:
                fixed = spec["fader"] * FIXED_ONE
            if fixed is not None:
                for off in FADER_AT:
                    if off < len(raw) - HEADER:
                        buf[HEADER + off] = fixed >> 24
                if FADER_FIXED_AT + 4 <= len(raw) - HEADER:
                    struct.pack_into("<I", buf, HEADER + FADER_FIXED_AT, fixed)
            if "pan" in spec and PAN_AT < len(raw) - HEADER:
                buf[HEADER + PAN_AT] = spec["pan"]
            raw = bytes(buf)
            if raw != before and record.owner not in changed:
                changed.append(record.owner)
        out.append(raw)
    result = reassemble(data, out)
    require_valid(result)
    return result, sorted(changed)


def match_by_reference(src: bytes, dst: bytes) -> dict[int, int]:
    """dst owner -> src owner, paired on the channel-strip reference each carries.

    Repeated references are paired in order (a session has four ``Rack.cst`` channels), so the
    Nth Rack in the source lands on the Nth Rack in the target. Safer than trusting raw owner
    ids to line up, which they only do between sessions cut from the same template.
    """
    from .chains import channel_references

    def by_ref(data):
        out: dict[str, list[int]] = {}
        for owner, ref in sorted(channel_references(data).items()):
            out.setdefault(ref, []).append(owner)
        return out

    a, b = by_ref(src), by_ref(dst)
    pairs = {}
    for ref, dst_owners in b.items():
        for i, owner in enumerate(dst_owners):
            if ref in a and i < len(a[ref]):
                pairs[owner] = a[ref][i]
    return pairs


def match_by_label(src: bytes, dst: bytes) -> dict[int, int]:
    """dst owner -> src owner, paired on the mixer label (``Sub 1``, ``Aux 2``, ``Audio 5``).

    The strips with no ``.cst`` reference — the stack folders' ``Sub N``, the trigger auxes —
    are only reachable this way.
    """
    from .binding import channels

    a = {c.label: owner for owner, c in channels(src).items() if c.in_use}
    return {owner: a[c.label] for owner, c in channels(dst).items()
            if c.in_use and c.label in a}


def copy_levels(src: bytes, dst: bytes, by: str = "reference") -> tuple[bytes, dict]:
    """Carry fader+pan from one project onto another -> ``(project, report)``."""
    src_levels, dst_levels = read_levels(src), read_levels(dst)
    if by == "owner":
        pairs = {o: o for o in dst_levels if o in src_levels}
    elif by == "label":
        pairs = match_by_label(src, dst)
    else:
        pairs = match_by_reference(src, dst)

    want, unchanged = {}, 0
    for dst_owner, src_owner in pairs.items():
        if dst_owner not in dst_levels or src_owner not in src_levels:
            continue
        s, d = src_levels[src_owner], dst_levels[dst_owner]
        fixed = s["fader_fixed"] if s["fader_fixed"] >> 24 == s["fader"] else s["fader"] * FIXED_ONE
        if fixed == d["fader_fixed"] and s["fader"] == d["fader"] and s["pan"] == d["pan"]:
            unchanged += 1
            continue
        want[dst_owner] = {"fader_fixed": fixed, "pan": s["pan"]}
    out, changed = set_levels(dst, want)
    # a project carries hundreds of pre-allocated Environment channels with no mixer presence;
    # only the ones carrying a strip reference are worth reporting as a miss
    from .chains import channel_references
    referenced = set(channel_references(dst))
    return out, {"matched": len(pairs), "changed": changed, "unchanged": unchanged,
                 "unmatched": sorted(referenced - set(pairs))}
