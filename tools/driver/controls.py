#!/usr/bin/env python3
"""Read every plug-in's Controls view on a track's channel strip in Logic Pro, and save nothing.

    python3 tools/driver/controls.py BUNDLE TRACK [TRACK…]

Opens BUNDLE in Logic Pro, presses Skip All / Continue / OK on its load-time dialogs, closes
floating windows, and for each TRACK: clicks its header, finds the inspector's channel strip,
opens each plug-in slot's window, switches it to the Controls view, reads every row's label,
display and slider value, and closes the window again. The project is then closed without
saving. Prints one JSON object:

    {"bundle": "...", "tracks": [{"track": "Audio 1", "strip": "Audio 1",
      "slots": [{"short": "Channel EQ", "rows": [{"label": "Gain", "display": "+2.0 dB", "slider": "62"}, …]}]}],
     "problems": ["…"]}

Drives Logic through macOS accessibility (`axdump.swift`, `axact.swift`) and real mouse clicks
(`click.swift`), never through Logic's own scripting, which hangs it. The traps it carries
from the measuring scripts: a window that opens before its view menu is ready reads no rows
(read twice); floating windows must go before `window 1` is the project; the pointer is parked
on the title bar after each click so no help tag becomes the first window.
"""
import json
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SE = 'tell application "System Events" to tell process "Logic Pro" to '
TRACK_ROW = re.compile(r"\s*(w0\.7\.1\.0\.1\.0\.0\.\d+) AXLayoutItem \| d=(Track [^|]*)\| t=[^|]*\| v=[^|]*\| @(-?\d+),(-?\d+) (\d+)x(\d+)")
STRIP = re.compile(r"\s*(w0\.6\.0\.2\.0\.\d+) AXLayoutItem \| d=([^|]*)\|")
CONTROL_ROW = re.compile(r"\s*w0\.(\d+)\.0\.(\d+)\.0\.(\d) (AXStaticText|AXGroup|AXSlider|AXCheckBox) \| d=[^|]*\| t=[^|]*\| v=([^|]*)\|")
DISMISS = ('tell application "System Events" to tell process "Logic Pro"\nset frontmost to true\n'
           'repeat with b in {"Skip All", "Continue", "OK"}\nrepeat with w in windows\n'
           'try\nclick button b of w\nend try\ntry\nclick button b of sheet 1 of w\nend try\nend repeat\nend repeat\n'
           'return (name of every window) as text\nend tell')
CLOSE = ('tell application "System Events" to tell process "Logic Pro"\n'
         'if (count of windows) is 0 then return "no window"\nperform action "AXRaise" of window 1\n'
         'keystroke "w" using command down\ndelay 2\nrepeat with w in windows\ntry\nclick button "Don’t Save" of w\nend try\n'
         'try\nclick button "Don’t Save" of sheet 1 of w\nend try\nend repeat\nreturn (name of every window) as text\nend tell')


def tool(name: str) -> list[str]:
    built = HERE / "bin" / name
    return [str(built)] if built.exists() else ["swift", str(HERE / f"{name}.swift")]


def sh(*args, timeout: int = 180) -> str:
    r = subprocess.run([str(a) for a in args], capture_output=True, text=True, timeout=timeout)
    return (r.stdout + r.stderr).strip()


def osa(script: str) -> str:
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=120)
    return (r.stdout or r.stderr).strip()


def names() -> list[str]:
    out = osa(SE + "get name of every window")
    return [n for n in out.split(", ") if n]


def dump(depth: int = 14, window: int = 0) -> str:
    return sh(*tool("axdump"), depth, window)


def press(path: str) -> str:
    return sh(*tool("axact"), "press", path)


def click(x: int, y: int) -> None:
    sh(*tool("click"), x, y)
    time.sleep(0.6)
    osa(SE + "set frontmost to true")


def wait_open(stem: str) -> bool:
    for _ in range(60):
        if any(stem in n for n in names()):
            time.sleep(8)
            return True
        time.sleep(1)
    return False


def close_floaters() -> list[str]:
    """Close plug-in and floating windows in front of the Tracks window by their close button."""
    closed = []
    for _ in range(8):
        front = names()[:1]
        if not front or front[0].endswith("- Tracks"):
            break
        head = dump(1, 0).splitlines()
        if len(head) < 2 or "d=close" not in head[1]:
            break
        press("w0.0")
        closed.append(front[0])
        time.sleep(0.8)
    return closed


def track_rows() -> list[tuple[str, str, int, int, int, int]]:
    out = []
    for ln in dump(12).splitlines():
        m = TRACK_ROW.match(ln)
        if m:
            out.append((m.group(1), m.group(2).strip(), *map(int, m.group(3, 4, 5, 6))))
    return out


def select_track(label: str) -> str | None:
    """Click the header named exactly ``label`` ("Audio 1" is not "Audio 10")."""
    for _path, desc, x, y, _w, h in track_rows():
        m = re.search(r"[“\"](.*)[”\"]\s*$", desc)
        if (m.group(1) if m else desc) == label:
            click(x + 40, y + h // 2)
            time.sleep(1.0)
            return desc
    return None


def strip_groups(which: int = 0) -> tuple[str | None, list[tuple[str, str]]]:
    """(an inspector strip's name, [(group path, slot short name)] top to bottom): the selected
    track's strip (0) or the output's beside it (1)."""
    tree = dump(14).splitlines()
    strips = [m for ln in tree if (m := STRIP.match(ln))]
    strip = strips[which] if which < len(strips) else None
    if strip is None:
        return None, []
    base = strip.group(1)
    found = []
    for ln in tree:
        m = re.match(r"\s*(" + re.escape(base) + r"\.\d+) AXGroup \| d=([^|]*)\| t=[^|]*\| v=[^|]*\| @(-?\d+),(-?\d+) ", ln)
        if m and "automation" not in m.group(2) and m.group(2).strip():
            found.append((int(m.group(4)), m.group(1), m.group(2).strip()))
    return strip.group(2).strip(), [(path, short) for _y, path, short in sorted(found)]


def ensure_controls_view() -> None:
    head = dump(1, 0).splitlines()
    view = next((ln.split()[0] for ln in head if "AXMenuButton | d=view" in ln), None)
    if view and "t=Controls" not in next(ln for ln in head if ln.split()[0] == view):
        sh(*tool("axact"), "pick", view, "~Control")
        time.sleep(2)


def control_rows() -> list[dict]:
    rows: dict[tuple[int, int], dict] = {}
    for ln in dump(8, 0).splitlines():
        m = CONTROL_ROW.match(ln)
        if m:
            rows.setdefault((int(m.group(1)), int(m.group(2))), {})[m.group(3)] = m.group(5).strip()
    return [{"label": v.get("0", "").rstrip(":"), "display": v.get("1", ""), "slider": v.get("2", "")}
            for _k, v in sorted(rows.items())]


def read_slot(path: str) -> list[dict]:
    for _attempt in range(2):                     # a window open before its view menu is ready reads no rows
        press(path + ".1")
        time.sleep(2.5)
        ensure_controls_view()
        time.sleep(1.5)
        rows = control_rows()
        close_floaters()
        time.sleep(0.8)
        if rows:
            return rows
    return []


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    bundle, tracks = Path(argv[0]), argv[1:]
    out = {"bundle": str(bundle), "tracks": [], "problems": []}
    if any(bundle.glob("Alternatives/*/Autosave*")):           # Logic would ask which version to open
        out["problems"].append(f"{bundle.name} carries an Autosave; pass a copy without one")
        print(json.dumps(out))
        return 1
    open_docs = [n for n in names() if n.endswith("- Tracks")]
    if open_docs:                                              # the dismiss and close steps reach every window
        out["problems"].append(f"Logic has a project open: {open_docs}; close it first")
        print(json.dumps(out))
        return 1
    subprocess.run(["open", "-a", "Logic Pro", str(bundle.resolve())], check=True)
    if not wait_open(bundle.stem):
        out["problems"].append(f"{bundle.stem} did not open; windows {names()}")
        print(json.dumps(out))
        return 1
    osa(DISMISS)
    time.sleep(1.5)
    close_floaters()
    for track in tracks:
        entry = {"track": track, "strip": None, "slots": []}
        if select_track(track) is not None:
            strip, groups = strip_groups()
        elif strip_groups(1)[0] == track:            # the output has no track header; its strip is the inspector's second
            strip, groups = strip_groups(1)
        else:
            out["problems"].append(f"no track header matching {track!r}: {[d for _p, d, *_r in track_rows()][:12]}")
            out["tracks"].append(entry)
            continue
        entry["strip"] = strip
        for path, short in groups:
            rows = read_slot(path)
            if not rows:
                out["problems"].append(f"{track}: {short!r} showed no Controls rows")
            entry["slots"].append({"short": short, "rows": rows})
        out["tracks"].append(entry)
    if names()[:1] and bundle.stem in names()[0]:              # close our document, never another
        osa(CLOSE)
        time.sleep(2)
    if any(bundle.stem in n for n in names()):
        out["problems"].append(f"{bundle.stem} is still open")
    print(json.dumps(out))
    return 1 if out["problems"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
