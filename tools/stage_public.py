"""Stage Logic saves from out/scratch into tests/corpus/ and the tracked public manifest.

    python3 tools/stage_public.py spec.json

spec: [{"save": "<bundle name under out/scratch>", "name": "<public bundle name>",
        "key": "<manifest key>", "note": "...", "facts": {...}}, ...]
One alternative per save, without its WindowImage or Autosave; Resources/ProjectInformation.plist
kept. A save is refused unless every project title in it carries the neutral prefix, and a name,
key or note is refused when it holds a word of `LOGICXKIT_PRIVATE_WORDS` (the environment or `.env`).
"""
import json
import os
import plistlib
import re
import shutil
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRATCH, CORPUS, MANIFEST = ROOT / "out/scratch", ROOT / "tests/corpus", ROOT / "tests/goldens/manifest.json"
NEUTRAL = ("CLAUDE ", "{PROJECT_NAME}")
SKIP = shutil.ignore_patterns("WindowImage*", "Autosave*", "Project File Backups")


def private_words() -> list[str]:
    raw = os.environ.get("LOGICXKIT_PRIVATE_WORDS")
    if raw is None:
        env = ROOT / ".env"
        for line in env.read_text().splitlines() if env.exists() else []:
            if line.startswith("LOGICXKIT_PRIVATE_WORDS="):
                raw = line.partition("=")[2].strip().strip("'\"")
    return [w.strip() for w in (raw or "").split(",") if w.strip()]


def leaks(text: str, words: list[str]) -> list[str]:
    """Words found in ``text``, case and separators aside."""
    return [w for w in words
            if re.search(r"[^A-Za-z0-9]*".join(re.escape(t) for t in re.split(r"[^A-Za-z0-9]+", w) if t), text, re.I)]


def titles(bundle: Path) -> list[str]:
    """The project title of every alternative: ``VariantNames`` is a dict keyed by alternative."""
    with (bundle / "Resources/ProjectInformation.plist").open("rb") as f:
        names = plistlib.load(f).get("VariantNames", {})
    return [str(t) for t in (names.values() if isinstance(names, dict) else names)]


def unneutral(bundle: Path) -> list[str]:
    return [t for t in titles(bundle) if not (t.startswith(NEUTRAL[0]) or t == NEUTRAL[1])]


def refuse(item: dict, why: str) -> None:
    sys.exit(f"REFUSED {item['save']!r}: {why}")


BOOK = b"book"
STRING, U64, DATE = 0x0101, 0x0304, 0x0400
UUID = re.compile(rb"[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}")
ZERO_UUID = b"00000000-0000-0000-0000-000000000000"


def bookmark_items(raw: bytes):
    """(payload offset, length, type) of every item of every macOS bookmark (`book` blob) in
    ``raw``: its header's data offset leads to the TOC offset, the items run up to it."""
    at = raw.find(BOOK)
    while at >= 0:
        if at + 16 <= len(raw):
            total, _version, hdr = struct.unpack_from("<III", raw, at + 4)
            if 16 <= hdr < total <= len(raw) - at:
                end = at + hdr + struct.unpack_from("<I", raw, at + hdr)[0]
                pos = at + hdr + 4
                while end <= at + total and pos + 8 <= end:
                    length, kind = struct.unpack_from("<II", raw, pos)
                    if pos + 8 + length > end:
                        break
                    yield pos + 8, length, kind
                    pos += 8 + ((length + 3) & ~3)
        at = raw.find(BOOK, at + 4)


def scrub_bookmarks(raw: bytes) -> tuple[bytes, int]:
    """``raw`` with its bookmarks' identifying fields blanked at the same length: the path
    component after `Users` (the account), every UUID (the volume's), every u64 (file ids, the
    volume's size) and date. Space Designer names its impulse response by one. -> (bytes, count)"""
    buf, n, prev = bytearray(raw), 0, None
    for pos, length, kind in list(bookmark_items(raw)):
        body = raw[pos:pos + length]
        if kind == STRING:
            if prev == b"Users" and set(body) != {ord("x")}:
                buf[pos:pos + length], n = b"x" * length, n + 1
            elif UUID.fullmatch(body) and body != ZERO_UUID:
                buf[pos:pos + length], n = ZERO_UUID, n + 1
            prev = body
        elif kind in (U64, DATE) and any(body):
            buf[pos:pos + length], n = bytes(length), n + 1
    return bytes(buf), n


def bookmark_leaks(raw: bytes) -> int:
    """How many bookmark fields in ``raw`` still say something about the machine that saved it."""
    return scrub_bookmarks(raw)[1]


def scrub(raw: bytes, words: list[str]) -> tuple[bytes, dict[str, int]]:
    """``raw`` with every home-directory prefix and every private word replaced in place at the
    same length — the home becomes `/Library/--…/`, a word becomes `x`s — so a machine's own
    string inside a record (Space Designer names its IR by path) ships neutral with the record's
    layout unmoved. A plist's base64 ``<data>`` spans are left alone: a short word matches their
    text by chance and the change corrupts the blob (a zlib state stopped inflating), and what
    they encode is checked by decoding it, not by grep. Returns how many of each were replaced."""
    counts: dict[str, int] = {}

    def home(m: re.Match) -> bytes:
        n = len(m.group(0))
        neutral = b"/Library/" + b"-" * max(n - 10, 0) + b"/"
        return neutral if len(neutral) == n else (b"/Library/" + b"-" * n)[:n]

    def outside(text: bytes) -> bytes:
        text, k = re.subn(rb"/Users/[^/\x00]+/", home, text)
        if k:
            counts["home paths"] = counts.get("home paths", 0) + k
        for word in words:
            text, k = re.subn(re.escape(word.encode()), lambda m: b"x" * len(m.group(0)), text, flags=re.I)
            if k:
                counts["private words"] = counts.get("private words", 0) + k
        return text

    pieces, at = [], 0
    for m in re.finditer(rb"<data>.*?</data>", raw, flags=re.S):
        pieces += [outside(raw[at:m.start()]), m.group(0)]
        at = m.end()
    pieces.append(outside(raw[at:]))
    out, marked = scrub_bookmarks(b"".join(pieces))
    if marked:
        counts["bookmark fields"] = marked
    return out, counts


def main(spec_path: Path) -> int:
    words = private_words()
    spec = json.loads(spec_path.read_text())
    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {
        "_about": "Public goldens: Logic's own saves of a blank project, one change per save, tracked "
                  "under tests/corpus/. Paths are relative to that directory. Facts are what tests may assert."}
    for item in spec:
        src = SCRATCH / item["save"]
        if bad := unneutral(src):
            refuse(item, f"project title(s) {bad} lack the neutral prefix; Save As under a 'CLAUDE …' name first")
        for field in ("name", "key", "note"):
            if hit := leaks(str(item.get(field, "")), words):
                refuse(item, f"{field} carries a private word: {hit}")
        alt = sorted(src.glob("Alternatives/*"))[0]
        dst = CORPUS / item["name"]
        if dst.exists():
            shutil.rmtree(dst)
        (dst / "Alternatives").mkdir(parents=True)
        shutil.copytree(alt, dst / "Alternatives" / alt.name, ignore=SKIP)
        (dst / "Resources").mkdir()
        shutil.copy2(src / "Resources/ProjectInformation.plist", dst / "Resources/ProjectInformation.plist")
        scrubbed: dict[str, int] = {}
        for f in sorted(p for p in dst.rglob("*") if p.is_file()):
            clean, counts = scrub(f.read_bytes(), words)
            if counts:
                f.write_bytes(clean)
                scrubbed[str(f.relative_to(dst))] = counts
        manifest[item["key"]] = {"path": item["name"], "note": item["note"], "facts": item.get("facts", {})}
        if scrubbed:
            manifest[item["key"]]["scrubbed"] = scrubbed
        print(f"  {item['key']:34s} <- {item['save']}" + (f"  (scrubbed {scrubbed})" if scrubbed else ""))
    MANIFEST.write_text(json.dumps(manifest, indent=1) + "\n")
    print(f"{len(spec)} staged; manifest has {len(manifest) - 1} keys")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
