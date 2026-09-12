"""Where Logic's own files live: its user folder, the saved-strip library, the installed app.

`~/Music/Audio Music Apps` holds `Channel Strip Settings` and `Plug-In Settings` as siblings,
so a `.cst` spec and a `.pst` spec hang off different roots, and only the strip one is what
`strip_root` means. `LOGICXKIT_AUDIO_MUSIC_APPS`, `LOGICXKIT_STRIP_ROOT` and
`LOGICXKIT_LOGIC_APP` override the three defaults; an absolute path in a spec always wins.
"""

from __future__ import annotations

import os
from pathlib import Path

from ...utils.env import env_path

USER_DATA_ENV = "LOGICXKIT_AUDIO_MUSIC_APPS"
USER_DATA_DEFAULT = Path.home() / "Music/Audio Music Apps"
ENV = "LOGICXKIT_STRIP_ROOT"
DEFAULT = USER_DATA_DEFAULT / "Channel Strip Settings"
APP_ENV = "LOGICXKIT_LOGIC_APP"
APP_DEFAULT = Path("/Applications/Logic Pro.app")


def logic_user_data() -> Path:
    """Logic's own user folder: the base for a `.pst` spec's `output_dir`."""
    return env_path(USER_DATA_ENV, USER_DATA_DEFAULT)


def strip_library() -> Path:
    """The saved-strip library: the base for a `.cst` spec's paths."""
    return env_path(ENV, logic_user_data() / "Channel Strip Settings")


def logic_app() -> Path:
    return env_path(APP_ENV, APP_DEFAULT)


def factory_settings() -> Path:
    """Logic's bundled plug-in settings — the factory default a `.pst` is patched from, and
    the only place the GAMETSPP type ids can be mapped back to plugin folder names."""
    return logic_app() / "Contents/Resources/Plug-In Settings"


def resolve(path, root=None) -> Path:
    """A spec path against its `strip_root`, or the strip library when the spec names none."""
    p = Path(path).expanduser()
    if p.is_absolute():
        return p
    return (Path(os.path.expanduser(str(root))) if root else strip_library()) / p


def require_plain_names(names) -> None:
    """A preset name becomes ``<name>.cst`` or ``.pst`` in an output directory; a separator
    would escape it."""
    bad = [n for n in names if not n or n in (".", "..") or "/" in n or "\\" in n]
    if bad:
        raise ValueError(f"preset names must each be a plain file name: {bad}")


def under_live_library(path) -> bool:
    """Whether a path lands inside Logic's user folder: the configured one, or the default,
    which Logic loads whatever `LOGICXKIT_AUDIO_MUSIC_APPS` says."""
    p = Path(os.path.expanduser(str(path))).resolve()
    return any(p.is_relative_to(root.resolve()) for root in (logic_user_data(), USER_DATA_DEFAULT))
