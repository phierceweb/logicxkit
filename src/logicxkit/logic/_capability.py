"""One row of the capability table (`_capabilities.py`)."""

from __future__ import annotations

from dataclasses import dataclass

from .services.stream.validate import MEASURED_FORMAT


@dataclass(frozen=True)
class Capability:
    commands: tuple[str, ...]
    level: str
    safe: str
    catch: str = ""
    derived: tuple[str, ...] = ()      # argument dests whose writes are DERIVED whatever the row's level
    formats: tuple[int, ...] = (MEASURED_FORMAT,)   # file format words the commands write; the catch names the saves
