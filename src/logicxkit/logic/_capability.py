"""One row of the capability table (`_capabilities.py`)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Capability:
    commands: tuple[str, ...]
    level: str
    safe: str
    catch: str = ""
    derived: tuple[str, ...] = ()      # argument dests whose writes are DERIVED whatever the row's level
