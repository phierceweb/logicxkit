"""Environment overrides where an empty value counts as unset.

`bin/run` sources `.env`, and `.env.example` carries every optional key with no value — so
`os.environ.get(name, default)` hands back `""`, and a path override collapses to the process's
working directory instead of falling back. Every override in this repo goes through here.
"""

from __future__ import annotations

import os
from pathlib import Path


def env_str(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name) or default


def env_path(name: str, default) -> Path:
    """An override as a path with `~` expanded, or ``default`` when unset or empty."""
    return Path(os.path.expanduser(env_str(name, str(default))))
