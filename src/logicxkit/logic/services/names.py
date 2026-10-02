"""What a written name may hold, whichever record keeps it: UTF-8 as Logic stores one, with no
control character, line separator or direction control."""

from __future__ import annotations

import unicodedata

# line and paragraph separators and the bidi controls; joiners, variation selectors and the
# direction marks right-to-left text uses stay
TURNS_THE_LINE = set("\u2028\u2029\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")
BLANK = set("\u115f\u1160\u3164\uffa0\u2800")    # letters and a symbol by category, nothing on screen


def readable(raw: bytes) -> str | None:
    """UTF-8, as Logic writes it; None for other bytes or a control character."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return None if any(ord(ch) < 32 or 127 <= ord(ch) < 160 for ch in text) else text


def written(name: str, what: str, *, limit: int | None = None, empty: bool = False) -> bytes:
    """``name`` as the bytes to store, or ValueError naming ``what`` (`a track name`): at most
    ``limit`` bytes, a visible character unless ``empty`` allows none at all."""
    try:
        encoded = name.encode("utf-8")
    except UnicodeEncodeError:
        encoded = None
    size = f"1-{limit} bytes" if limit and not empty else f"at most {limit} bytes" if limit else "text"
    if encoded is None or readable(encoded) is None or (limit and len(encoded) > limit) or not (encoded or empty):
        raise ValueError(f"{what} is {size} of UTF-8 with no control character")
    if TURNS_THE_LINE & set(name) or (name and all(ch in BLANK or unicodedata.category(ch)[0] in "ZC" for ch in name)):
        raise ValueError(f"{what} needs a visible character and takes no line separator or "
                         "direction control")
    return encoded
