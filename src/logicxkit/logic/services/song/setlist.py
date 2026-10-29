"""A setlist file: one song per line in playing order; a line reading ``break`` (any case) is a
stop the band took after the song before it; blank lines and lines starting with ``#`` are
skipped, so a song may carry a ``#`` in its name."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

BREAK = "break"


@dataclass(frozen=True)
class Setlist:
    songs: tuple[str, ...]
    breaks: frozenset[int]          # after song i, 1-based

    def __len__(self) -> int:
        return len(self.songs)


def parse_setlist(text: str) -> Setlist:
    songs: list[str] = []
    breaks: set[int] = set()
    for k, raw in enumerate(text.splitlines(), 1):
        line = raw.strip().strip("\ufeff").strip()
        if not line or line.startswith("#"):
            continue
        if line.lower() == BREAK:
            if not songs:
                raise ValueError(f"line {k}: a break before the first song")
            if len(songs) in breaks:
                raise ValueError(f"line {k}: two breaks in a row")
            breaks.add(len(songs))
            continue
        if any(ord(c) < 32 for c in line):
            raise ValueError(f"line {k}: a control character in the name")
        songs.append(line)
    if not songs:
        raise ValueError("the setlist names no song")
    return Setlist(tuple(songs), frozenset(breaks))


def read_setlist(path: Path) -> Setlist:
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except OSError as e:
        raise ValueError(f"{path}: {e}") from None
    except UnicodeDecodeError:
        raise ValueError(f"{path}: not UTF-8 text") from None
    try:
        return parse_setlist(text)
    except ValueError as e:
        raise ValueError(f"{path}: {e}") from None
