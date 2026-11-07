"""`chains --verify`'s third-party slots: each one's AU state read by the plug-in itself through the
headless host and compared with the bytes (`au/services/state_check.py`), no Logic needed."""

from __future__ import annotations

from ...au.services.embed import find_au_plists
from ...au.services.host import AuHost, AuHostError
from ...au.services.state_check import check_state, checkable
from ..services.mixer.plugins import slot_payloads


def third_party_states(data: bytes, tracks: list[str]) -> dict[str, list[dict | None]]:
    """Per track label, each third-party audio slot's AU state in slot order (None without one)."""
    out: dict[str, list[dict | None]] = {t: [] for t in tracks}
    for ref, payload in slot_payloads(data):
        if ref.channel in out and not ref.midi and not ref.native:
            out[ref.channel].append(next((pl for _off, pl in find_au_plists(payload) if "manufacturer" in pl), None))
    return out


def host_line(where: str, plist: dict | None, host: AuHost | None) -> tuple[str, int]:
    """A third-party slot read through the headless AU host (`state_check`): the line and how many
    rows differ. A slot the host cannot read here is not compared, which is no difference."""
    try:
        if host is None or plist is None or not checkable(plist):
            return f"{where}: third-party, not compared", 0
        found = check_state(plist, host)
    except AuHostError as e:
        return f"{where}: third-party, not compared (AU host: {e})", 0
    except ValueError as e:                                   # a state whose bytes do not parse (`FfpError`)
        return f"{where}: third-party, not compared ({e})", 0
    if found.differ:
        return (f"{where}: {len(found.differ)} differ, {found.agreed} agree through the AU host: "
                + "; ".join(found.differ), len(found.differ))
    return f"{where}: matched through the AU host, {found.agreed} parameter(s)", 0
