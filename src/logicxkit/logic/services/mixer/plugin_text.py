"""A text state (Alchemy, Sample Alchemy): after the marker `46ia` the slot keeps Alchemy's own
`Key = value` lines in `<section>` blocks; a table with `"state": "text"` names a row by key."""

from __future__ import annotations

TEXT_MARK = b"46ia"                  # the state is text from 6 bytes past it: Alchemy's `.acp` lines


def text_state(payload: bytes) -> dict[str, str]:
    """A text state's `Key = value…` lines as `section[n].key` -> value text: a `<tag>` line opens
    a section, numbered by how often its tag has appeared (Alchemy's four `<source>`s repeat
    every key). A re-save's appended second copy counts on from there."""
    at = payload.find(TEXT_MARK)
    if at < 0:
        return {}
    out: dict[str, str] = {}
    seen: dict[bytes, int] = {}
    section = ""
    for line in payload[at + 6:].split(b"\r\n"):
        if line.startswith(b"<") and line.endswith(b">"):
            tag = line[1:-1]
            seen[tag] = seen.get(tag, 0) + 1
            section = f"{tag.decode('latin-1')}[{seen[tag]}]."
            continue
        key, sep, value = line.partition(b" = ")
        if sep:
            name = section + key.decode("latin-1")
            while name in out:
                name += "'"
            out[name] = value.decode("latin-1")
    return out
