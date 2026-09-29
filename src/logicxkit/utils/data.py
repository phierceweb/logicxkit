"""Where the data lives: Logic-written record templates, the plugin-slot donor library, the
translation maps and the AU parameter tables. The maps and the native parameter tables are
measured and written here; Logic and the plugin vendors wrote the rest. The package's own file
wins; the data root supplies what the package lacks, so a checkout runs what a wheel runs:

    logicxkit/data/         the package's own copy: `logic/` templates and native parameter
                            tables, `donors/` native plug-ins only, `translate/` maps
    LOGICXKIT_DATA          the data root, an env override, absolute
    <repo>/resources/data   its default, gitignored; see resources/data/README.md

    <root>/donors/*.slot     third-party donors and their manifest (`logic donors` harvests them)
    <root>/logic/*.json      record templates the package lacks
    <root>/translate/*.json  translation maps the package lacks (`services/translate`)
    <root>/au/*.json         AU parameter tables (`au params` regenerates them) — root only
"""

from __future__ import annotations

from pathlib import Path

from .env import env_path, env_str

ENV = "LOGICXKIT_DATA"
KINDS = ("donors", "logic", "au", "translate")
PACKAGED = Path(__file__).resolve().parents[1] / "data"
PACKAGED_KINDS = ("donors", "logic", "translate")
DEFAULT_ROOT = Path(__file__).resolve().parents[3] / "resources" / "data"


class MissingData(FileNotFoundError):
    """A data file the operation needs is in neither the data root nor the package."""


def data_root() -> Path:
    return env_path(ENV, DEFAULT_ROOT)


def writable_root() -> Path:
    """The data root a harvest writes into. An installed copy's default resolves beside
    site-packages, where what is written vanishes with the venv, so there it must be named."""
    if not env_str(ENV) and not DEFAULT_ROOT.parent.is_dir():
        raise MissingData(f"no data root to write to: set {ENV}, or pass --library; the default "
                          f"({DEFAULT_ROOT}) is not in a checkout")
    return data_root()


def data_dir(kind: str) -> Path:
    if kind not in KINDS:
        raise ValueError(f"data kind {kind!r} is not one of {KINDS}")
    return data_root() / kind


def data_dirs(kind: str) -> list[Path]:
    """Every directory holding ``kind``, the package first, the data root second."""
    candidates = ([PACKAGED / kind] if kind in PACKAGED_KINDS else []) + [data_dir(kind)]
    return [d for d in candidates if d.is_dir()]


def data_file(kind: str, name: str) -> Path:
    """One data file: the package's, else the data root's, else `MissingData` naming both."""
    for d in data_dirs(kind):
        if (d / name).exists():
            return d / name
    raise MissingData(f"{kind}/{name} is in neither {data_dir(kind)} ({ENV}) nor the package's "
                      "logicxkit/data — Logic- or vendor-written data; resources/data/README.md "
                      "says how each kind is made")


def have_data(kind: str, *names: str) -> bool:
    return any(all((d / n).exists() for n in names) for d in data_dirs(kind))
