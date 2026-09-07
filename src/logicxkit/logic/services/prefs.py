"""Logic's application settings — the behaviours that are not in any project.

`~/Library/Preferences/com.apple.logic10.plist`, read key by key and written through
`defaults` so the values go through cfprefsd rather than a stale file. Logic keeps its own
copy while it runs and writes it back on quit, so a write is refused while Logic is open.
The names below are the Settings window's; every key was pinned by toggling that one
control, closing the Settings window (which is when Logic flushes most of them) and
diffing `defaults read` (2026-09-05, Logic 12.3.1). Keys ending in `_n`, `Disabled` and
`Lock...` store the box unticked.

`CLgTransportDefaultConfiguration` is what the control bar's Save As Defaults stores: the
same five lists and display mode a project carries (`controlbar.py`).
"""

from __future__ import annotations

import plistlib
import subprocess
from pathlib import Path

from ...utils.env import env_path
from .prefs_table import BY_KEY, BY_NAME, SETTINGS, Setting  # noqa: F401 — the table's home

DOMAIN = "com.apple.logic10"
ENV_PLIST = "LOGICXKIT_LOGIC_PREFS"
PREFS_DIR = Path.home() / "Library/Preferences"
CONTROLBAR_DEFAULT_KEY = "CLgTransportDefaultConfiguration"


def prefs_plist(domain: str = DOMAIN) -> Path:
    """The settings file itself. `LOGICXKIT_LOGIC_PREFS` names a copy to read instead of
    Logic's own; a scratch `domain` gets its own file either way."""
    if domain == DOMAIN:
        return env_path(ENV_PLIST, PREFS_DIR / f"{DOMAIN}.plist")
    return PREFS_DIR / f"{domain}.plist"




def logic_running() -> bool:
    return subprocess.run(["pgrep", "-x", "Logic Pro"], capture_output=True).returncode == 0


def _read_key(key: str, domain: str = DOMAIN) -> str | None:
    """One value through cfprefsd, as `defaults read` prints it; None when unset."""
    out = subprocess.run(["defaults", "read", domain, key], capture_output=True, text=True)
    return out.stdout.strip() if out.returncode == 0 else None


def data_bytes(text) -> bytes:
    """A data value as `defaults read` prints it (`{length = 16, bytes = 0x071f... }`), or bytes."""
    if isinstance(text, (bytes, bytearray)):
        return bytes(text)
    hexes = str(text).split("bytes = ", 1)[1] if "bytes = " in str(text) else str(text)
    return bytes.fromhex("".join(ch for ch in hexes.replace("0x", "") if ch in "0123456789abcdefABCDEF"))


def decode(s: Setting, raw):
    """One setting's value from its stored form."""
    text = str(raw).strip()
    if s.kind == "bool":
        on = text.lower() in ("1", "true", "yes")
        return (not on) if s.inverted else on
    if s.kind == "choice":
        return s.choice_of(raw)
    if s.kind == "str":
        return text
    if s.kind == "float":
        return float(text)
    if s.kind == "bit":
        return bool(int(text) & s.mask)
    if s.kind == "databit":
        blob = data_bytes(raw)
        return bool(blob[s.offset] & s.mask) if len(blob) > s.offset else None
    return int(text)


def read_settings(values: dict | None = None) -> dict[str, bool | int | str | None]:
    """name -> value for the settings this module knows: a bool, an int, a string, a choice's
    name; None when Logic has never written it. ``values`` (key -> raw value) stands in for
    the live settings in tests."""
    out = {}
    for s in SETTINGS:
        raw = values.get(s.key) if values is not None else _read_key(s.key)
        if raw is None and s.kind == "choice" and None in s.values:
            out[s.name] = s.choice_of(None)
        else:
            out[s.name] = None if raw is None else decode(s, raw)
    return out


def parse_value(name: str, text: str) -> bool | int | str:
    """A setting's value from the words a person writes: on/off, a number, or a choice."""
    s = BY_NAME[name]
    t = text.strip()
    if s.kind == "int":
        return int(t)
    if s.kind == "float":
        return float(t)
    if s.kind == "str":
        return t
    if s.kind == "choice":
        hits = [c for c in s.choices if c.lower() == t.lower()] or [c for c in s.choices if t.lower() in c.lower()]
        if len(hits) != 1:
            raise ValueError(f"{name!r}: choose one of {', '.join(s.choices)}")
        return hits[0]
    if t.lower() in ("on", "yes", "true", "1"):
        return True
    if t.lower() in ("off", "no", "false", "0"):
        return False
    raise ValueError(f"{name!r}: use on or off, not {text!r}")


def encode(s: Setting, value, current=None) -> tuple[str, str]:
    """The `defaults write` flag and text for ``value``; ``current`` is the stored value a
    flag kind edits into."""
    if s.kind == "bool":
        stored = (not value) if s.inverted else bool(value)
        return "-bool", "YES" if stored else "NO"
    if s.kind == "choice":
        stored = s.stored(value)
        if stored is None:
            return "-delete", ""
        if isinstance(stored, bool):
            return "-bool", "YES" if stored else "NO"
        if isinstance(stored, float):
            return "-float", repr(stored)
        return ("-string", stored) if isinstance(stored, str) else ("-int", str(stored))
    if s.kind == "str":
        return "-string", str(value)
    if s.kind == "float":
        return "-float", repr(float(value))
    if s.kind == "bit":
        n = int(str(current).strip()) if current is not None else 0
        n = (n | s.mask) if value else (n & ~s.mask)
        if s.width:
            n &= (1 << s.width) - 1
            if n & (1 << (s.width - 1)):
                n -= 1 << s.width
        return "-int", str(n)
    if s.kind == "databit":
        blob = bytearray(data_bytes(current) if current is not None else b"")
        if len(blob) <= s.offset:
            raise ValueError(f"{s.name!r}: {s.key} is not written yet — set it in Logic once first")
        blob[s.offset] = (blob[s.offset] | s.mask) if value else (blob[s.offset] & ~s.mask & 0xFF)
        return "-data", blob.hex()
    return "-int", str(int(value))


def write_settings(want: dict[str, bool | int | str], domain: str = DOMAIN) -> None:
    """Set the named settings through `defaults write`; refused while Logic runs, since Logic
    would write its own copy back over them on quit."""
    if domain == DOMAIN and logic_running():
        raise RuntimeError("Logic Pro is running — quit it first, or it will overwrite the change on quit")
    for name, value in want.items():
        s = BY_NAME[name]
        current = _read_key(s.key, domain) if s.kind in ("bit", "databit") else None
        flag, text = encode(s, value, current)
        if flag == "-delete":
            subprocess.run(["defaults", "delete", domain, s.key], check=False)
        else:
            subprocess.run(["defaults", "write", domain, s.key, flag, text], check=True)


def backup(into: Path, domain: str = DOMAIN) -> Path:
    """A copy of the settings file, named by the time, under ``into``."""
    import shutil
    import time

    into.mkdir(parents=True, exist_ok=True)
    path = into / f"{domain}.{time.strftime('%Y%m%d-%H%M%S')}.plist"
    shutil.copy2(prefs_plist(domain), path)
    return path


def controlbar_default(values: dict | None = None, domain: str = DOMAIN) -> dict | None:
    """The control bar Save As Defaults set, in the project layout's shape, if any — read from
    the settings file (`defaults export` cannot: the file holds text XML rejects)."""
    if values is not None:
        d = values.get(CONTROLBAR_DEFAULT_KEY)
    else:
        out = subprocess.run(["plutil", "-extract", CONTROLBAR_DEFAULT_KEY, "json", "-o", "-",
                              str(prefs_plist(domain))],
                             capture_output=True, text=True)
        if out.returncode != 0:
            return None
        import json
        d = json.loads(out.stdout)
    return {k: (list(v) if isinstance(v, list) else v) for k, v in d.items()} if isinstance(d, dict) else None


def write_controlbar_default(layout: dict, domain: str = DOMAIN) -> None:
    """Make a project's control bar layout the default for new projects."""
    if domain == DOMAIN and logic_running():
        raise RuntimeError("Logic Pro is running — quit it first, or it will overwrite the change on quit")
    subprocess.run(["defaults", "write", domain, CONTROLBAR_DEFAULT_KEY, plist_fragment(layout)], check=True)


def plist_fragment(value) -> str:
    """``value`` as the XML property-list fragment `defaults write` takes for a typed
    dictionary — old-style `{ k = (1, 2); }` text would store every number as a string."""
    text = plistlib.dumps({k: (list(v) if isinstance(v, list) else v) for k, v in value.items()},
                          fmt=plistlib.FMT_XML).decode()
    return text[text.index("<dict>"):text.rindex("</dict>") + len("</dict>")]
