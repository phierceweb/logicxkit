"""Where the untracked data lives: Logic-written record templates, the plugin-slot donor
library and the AU parameter tables. None of it is authored here — Logic and the plugin
vendors wrote those bytes — so it stays out of the tracked tree, under one root:

    LOGICXKIT_DATA          env override, absolute
    <repo>/resources/data   the default, gitignored; see resources/data/README.md

    <root>/donors/*.slot     plugin-slot donors and their manifest (`logic donors` harvests them)
    <root>/logic/*.json      record templates Logic saved (aux, instrument, audio, group, section)
    <root>/au/*.json         AU parameter tables (`au params` regenerates them)
"""

from __future__ import annotations

from pathlib import Path

from .env import env_path

ENV = "LOGICXKIT_DATA"
KINDS = ("donors", "logic", "au")


class MissingData(FileNotFoundError):
    """A data file the operation needs is not present under the data root."""


def data_root() -> Path:
    return env_path(ENV, Path(__file__).resolve().parents[3] / "resources" / "data")


def data_dir(kind: str) -> Path:
    if kind not in KINDS:
        raise ValueError(f"data kind {kind!r} is not one of {KINDS}")
    return data_root() / kind


def data_file(kind: str, name: str) -> Path:
    """The path of one data file, or `MissingData` naming what to set."""
    p = data_dir(kind) / name
    if not p.exists():
        raise MissingData(f"{p} is missing — it is Logic- or vendor-written data kept outside the "
                          f"repo; set {ENV} to a directory that holds {kind}/{name} "
                          "(resources/data/README.md says how each kind is made)")
    return p


def have_data(kind: str, *names: str) -> bool:
    d = data_dir(kind)
    return d.is_dir() and all((d / n).exists() for n in names)
