"""Fetch the public golden corpus into resources/public/ (`bin/run fetch-corpus`).

`tests/goldens/corpus.json` pins the release asset's URL and sha256; nothing is written unless
the download matches, and every member must sit under `public/`.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIN = ROOT / "tests" / "goldens" / "corpus.json"


class CorpusError(RuntimeError):
    pass


def unpack(blob: bytes, sha256: str, resources: Path) -> int:
    """Unpack ``blob`` (a .tar.gz) under ``resources`` -> number of bundles; refuses first."""
    digest = hashlib.sha256(blob).hexdigest()
    if digest != sha256:
        raise CorpusError(f"checksum mismatch: got {digest}, pinned {sha256}")
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        members = tar.getmembers()
        for m in members:
            parts = Path(m.name).parts
            if not parts or parts[0] != "public" or ".." in parts or Path(m.name).is_absolute():
                raise CorpusError(f"refusing member outside public/: {m.name!r}")
        tar.extractall(resources, members=members, filter="data")
    return len({Path(m.name).parts[1] for m in members if len(Path(m.name).parts) > 1})


def main() -> int:
    if not PIN.exists():
        print(f"no corpus pinned yet ({PIN} is missing)")
        return 2
    pin = json.loads(PIN.read_text())
    resources = Path(os.environ.get("LOGICXKIT_RESOURCES") or ROOT / "resources").expanduser()
    print(f"fetching {pin['url']}")
    with urllib.request.urlopen(pin["url"], timeout=120) as r:  # noqa: S310 — pinned https URL
        blob = r.read()
    try:
        n = unpack(blob, pin["sha256"], resources)
    except CorpusError as e:
        print(f"refused: {e}")
        return 1
    print(f"{n} bundle(s) under {resources / 'public'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
