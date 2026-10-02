"""A track by the name a user types: `Drums`, or `Drums (Sub 1)` where a stack header and a
channel share the name — the mixer label in parentheses picks the row."""

from __future__ import annotations

import unicodedata


def _same(have: str | None, want: str) -> bool:
    """Names compare by their NFC form: a name pasted from a file path arrives decomposed."""
    nfc = unicodedata.normalize
    return have is not None and nfc("NFC", have) == nfc("NFC", want)


def rows_named(rows: list[dict], name: str) -> list[dict]:
    """The `read_tracks` rows ``name`` means. A trailing ``(LABEL)`` is a label only when a row
    has that name and label, so a track literally named `Pad (dry)` still matches itself."""
    wanted = name.strip()
    if wanted.endswith(")") and " (" in wanted:
        base, _, label = wanted[:-1].rpartition(" (")
        labelled = [r for r in rows if _same(r["name"], base) and r["label"] == label]
        if labelled:
            return labelled
    return [r for r in rows if _same(r["name"], wanted)]


def stacks_named(stacks: list, name: str) -> list:
    """Every stack called ``name``, in either Unicode form."""
    return [s for s in stacks if _same(s.name, name)]


def stack_named(stacks: list, name: str):
    """The stack ``name`` means, or None; two of that name need the strip, `Drums (Aux 9)`
    (anything carrying ``.name`` and ``.strip``), else a ValueError naming the choices."""
    wanted = name.strip()
    if wanted.endswith(")") and " (" in wanted:
        base, _, strip = wanted[:-1].rpartition(" (")
        labelled = [s for s in stacks_named(stacks, base) if s.strip == strip]
        if labelled:
            return labelled[0]
    hits = stacks_named(stacks, wanted)
    if len(hits) > 1:
        choices = ", ".join(f"{s.name} ({s.strip})" for s in hits)
        raise ValueError(f"{len(hits)} stacks named {wanted!r}; say which: {choices}")
    return hits[0] if hits else None


def one_object(rows: list[dict], name: str) -> int:
    """The one track object ``name`` means, or a ValueError naming the choices."""
    hits = rows_named(rows, name)
    ids = sorted({r["object_id"] for r in hits})
    if len(ids) == 1:
        return ids[0]
    if not ids:
        raise ValueError(f"no track named {name!r}")
    choices = ", ".join(f"{r['name']} ({r['label']})" for r in hits)
    raise ValueError(f"{len(ids)} tracks named {name!r}; say which: {choices}")
