"""Pair a template's tracks with a session's.

Sessions cut from a template keep its Environment object ids, so the id pairs 56/56 rows on
every session on hand; a track added or renamed since pairs by its mixer label, then by a
unique name. Each pair records the rule that made it, so a plan can say why.
"""

from __future__ import annotations

import re

from dataclasses import dataclass

from .stacks import read_tracks


@dataclass(frozen=True)
class Pair:
    template: dict            # a read_tracks row
    session: dict | None
    rule: str                 # "object", "label", "name" or "missing"


def _agree(a: dict, b: dict) -> bool:
    return a["name"] == b["name"] or a["label"] == b["label"]


def row_key(row: dict) -> str:
    """How a map names a row: ``Name (Label)``, the label breaking duplicate names."""
    return f"{row['name']} ({row['label']})" if row["label"] else str(row["name"])


def pair_rows(template_rows: list[dict], session_rows: list[dict],
              forced: dict[str, str | None] | None = None,
              known: dict[int, int] | None = None,
              excluded: set[str] | None = None) -> list[Pair]:
    """Every template row paired with at most one session row, in template order.

    ``forced`` maps session ``row_key`` -> template ``row_key`` (a map file, for projects of a
    different lineage), or -> None for a row the map leaves alone, which no rule may then
    claim; with a map the mixer-label rule is off, since across lineages it pairs unrelated
    tracks that merely share an ``Audio N``. ``known`` maps a session object id -> the
    template row's ``key`` for rows a writer made from that template row: they pair first,
    whatever they are called. ``excluded`` names template rows the map leaves out: they pair
    with nothing and are never added."""
    if excluded:
        template_keys = {row_key(t) for t in template_rows}
        missing = sorted(k for k in excluded if k not in template_keys)
        if missing:
            raise ValueError(f"map leaves out a template track that does not exist: {missing[0]!r}")
        template_rows = [t for t in template_rows if row_key(t) not in excluded]
    free = {r["key"]: r for r in session_rows}
    pairs: list[Pair] = []
    taken: set[int] = set()

    def claim(t: dict, rule: str, pick) -> bool:
        s = next((r for r in free.values() if r["key"] not in taken and pick(r)), None)
        if s is None:
            return False
        taken.add(s["key"])
        pairs.append(Pair(t, s, rule))
        return True

    by_template: dict[int, tuple[str, object]] = {}          # template row key -> (rule, picker)
    for oid, t_row in (known or {}).items():
        by_template[t_row] = ("made", lambda r, oid=oid: r["object_id"] == oid)
    if forced:
        seen = {}
        session_by_key = {row_key(r): r for r in session_rows}
        template_keys = {row_key(t) for t in template_rows}
        for s_key, t_key in forced.items():
            if s_key not in session_by_key:
                raise ValueError(f"map names a session track that does not exist: {s_key!r}")
            if t_key is None:
                taken.add(session_by_key[s_key]["key"])            # left alone: no rule may claim it
                continue
            if t_key not in template_keys:
                raise ValueError(f"map names a template track that does not exist: {t_key!r}")
            if t_key in seen:
                raise ValueError(f"map sends two tracks to {t_key!r}: {seen[t_key]!r} and {s_key!r}")
            seen[t_key] = s_key
            t_row = next(t["key"] for t in template_rows if row_key(t) == t_key)
            by_template.setdefault(t_row, ("map", lambda r, s_key=s_key: row_key(r) == s_key))
    pending = []
    for t in template_rows:
        named = by_template.get(t["key"])
        if named is None or not claim(t, *named):
            pending.append(t)
    template_rows_left, pending = pending, []
    for t in template_rows_left:
        if not claim(t, "object", lambda r, t=t: r["object_id"] == t["object_id"] and _agree(r, t)):
            pending.append(t)
    still = []
    for t in pending:
        if forced is not None or not (t["label"] and claim(t, "label", lambda r, t=t: r["label"] == t["label"])):
            still.append(t)
    names = {}
    for r in session_rows:
        names[r["name"]] = names.get(r["name"], 0) + 1
    for t in still:
        if not (names.get(t["name"]) == 1 and claim(t, "name", lambda r, t=t: r["name"] == t["name"])):
            pairs.append(Pair(t, None, "missing"))
    order = {t["key"]: i for i, t in enumerate(template_rows)}
    return sorted(pairs, key=lambda p: order[p.template["key"]])


def pair_tracks(template: bytes, session: bytes, *, template_count: int | None,
                session_count: int | None, forced: dict[str, str] | None = None,
                excluded: set[str] | None = None) -> list[Pair]:
    return pair_rows(read_tracks(template, template_count), read_tracks(session, session_count),
                     forced=forced, excluded=excluded)


_COMMENT = re.compile(r"\s{2,}#")
_SYNONYMS = {"guitar": "gtr", "guitars": "gtr", "vocals": "vox", "vocal": "vox", "voice": "vox",
             "slapback": "slap", "stereo": "master", "out": "", "fi": "", "-": ""}


def _norm(name: str | None) -> list[str]:
    out = []
    for tok in (name or "").lower().replace("/", " ").replace("_", " ").split():
        tok = _SYNONYMS.get(tok, tok)
        if tok:
            out.append(tok)
    return out


def _kind(row: dict) -> str:
    label = row["label"] or ""
    if row["grouping"] and label.startswith("Sub "):
        return "stack"
    return label.split(" ")[0] if label else "?"


def propose_map(template_rows: list[dict], session_rows: list[dict]) -> list[dict]:
    """A guess per session row at the template row it should become, with a confidence and
    the reason, for a person to correct. Kinds never cross (an aux never becomes an audio
    track); each template row is proposed at most once."""
    used: set[int] = set()
    out = []
    candidates = [t for t in template_rows if t["name"]]

    def take(s, t, confidence, why):
        used.add(t["key"])
        out.append({"session": row_key(s), "template": row_key(t), "confidence": confidence, "why": why})

    remaining = []
    for s in session_rows:
        if not s["name"]:
            continue
        same_kind = [t for t in candidates if _kind(t) == _kind(s) and t["key"] not in used]
        exact = [t for t in same_kind if _norm(t["name"]) == _norm(s["name"])]
        if exact:
            take(s, exact[0], "high", "same name")
        else:
            remaining.append(s)
    still = []
    for s in remaining:
        same_kind = [t for t in candidates if _kind(t) == _kind(s) and t["key"] not in used]
        toks = _norm(s["name"])
        # "Gtr 2" -> "Gtr 2 DI" (the DI is what gets recorded); "Vox 1" -> the first free vox track
        prefixed = [t for t in same_kind if _norm(t["name"])[:len(toks)] == toks]
        if prefixed:
            di = [t for t in prefixed if "di" in _norm(t["name"])]
            t = (di or prefixed)[0]
            take(s, t, "medium", f"name prefix; {len(prefixed)} candidate(s)" + (", DI preferred" if di and len(prefixed) > 1 else ""))
            continue
        scored = []
        for t in same_kind:
            tt = set(_norm(t["name"]))
            if not tt or not toks:
                continue
            j = len(tt & set(toks)) / len(tt | set(toks))
            if j >= 0.34:
                scored.append((j, t))
        if scored:
            j, t = max(scored, key=lambda x: x[0])
            take(s, t, "low", f"shares words with it ({j:.0%})")
        else:
            still.append(s)
    for s in still:
        out.append({"session": row_key(s), "template": None, "confidence": "none", "why": "no template track resembles it; left alone"})
    order = {row_key(s): i for i, s in enumerate(session_rows)}
    return sorted(out, key=lambda e: order[e["session"]])


def _quoted(key: str) -> str:
    """A row key as the map writes it: bare, or in double quotes when it would otherwise read
    as an arrow or a comment."""
    if " -> " in key or key.startswith("#") or '"' in key:
        return '"' + key.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return key


def _unquote(text: str) -> tuple[str, str]:
    """``(key, rest)`` from the start of a map line side: a quoted key up to its closing
    quote, else everything up to the first ' -> ' (or the end)."""
    if text.startswith('"'):
        out, i = [], 1
        while i < len(text):
            c = text[i]
            if c == "\\" and i + 1 < len(text):
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                return "".join(out), text[i + 1:]
            out.append(c)
            i += 1
        raise ValueError(f"map line with an unclosed quote: {text!r}")
    at = text.find(" -> ")
    return (text, "") if at < 0 else (text[:at], text[at:])


def format_map(entries: list[dict], template_rows: list[dict]) -> str:
    """The editable map file: one line per session track, ``->`` the template track."""
    lines = ["# session track -> template track. Edit the right-hand side; '(none)' leaves the track",
             "# alone. Names are 'Name (Mixer label)', in double quotes when they hold ' -> ' or start",
             "# with '#'. Two spaces and a '#' end a line's comment; lines starting with # are ignored.",
             "# Template tracks nobody maps to are listed below with a '+': added as new tracks where a",
             "# writer can. Change the '+' to '-' to leave one out.", ""]
    quoted = [(_quoted(e["session"]), _quoted(e["template"] or "(none)"), e) for e in entries]
    width = max(len(q[0]) for q in quoted) if quoted else 0
    for left, target, e in quoted:
        lines.append(f"{left:{width}s} -> {target:28s}  # {e['confidence']}: {e['why']}")
    claimed = {e["template"] for e in entries}
    unclaimed = [row_key(t) for t in template_rows if t["name"] and row_key(t) not in claimed]
    if unclaimed:
        lines += ["", "# template tracks nobody maps to: '+' adds, '-' leaves out"] + [f"+ {_quoted(k)}" for k in unclaimed]
    return "\n".join(lines) + "\n"


def parse_map(text: str) -> dict[str, str | None]:
    """Session ``row_key`` -> template ``row_key``, or None for a row marked ``(none)``."""
    return parse_map_full(text)[0]


def parse_map_full(text: str) -> tuple[dict[str, str | None], set[str]]:
    """``(forced, excluded)``: the session -> template pairs, and the template rows a
    ``- Name (Label)`` line leaves out (``+`` lines are the default and say nothing)."""
    forced, excluded = {}, set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = _COMMENT.split(line, 1)[0].strip()
        if line[:2] in ("+ ", "- "):
            key, tail = _unquote(line[2:].strip())
            if tail.strip() or not key.strip():
                raise ValueError(f"bad template-track line: {raw.strip()!r}")
            if line[0] == "-":
                excluded.add(key.strip())
            continue
        left, rest = _unquote(line)
        rest = rest.lstrip()
        if not rest.startswith("->"):
            raise ValueError(f"map line without '->': {raw.strip()!r}")
        right, tail = _unquote(rest[2:].strip())
        if tail.strip():
            raise ValueError(f"map line with more after the target: {raw.strip()!r}")
        left, right = left.strip(), right.strip()
        if right:
            forced[left] = None if right == "(none)" else right
    return forced, excluded


def extra_rows(pairs: list[Pair], session_rows: list[dict]) -> list[dict]:
    """Session rows no template row claimed."""
    used = {p.session["key"] for p in pairs if p.session is not None}
    return [r for r in session_rows if r["key"] not in used]


def match_quality(pairs: list[Pair]) -> float:
    """Fraction of template rows paired by Environment object id.

    A session cut from the template keeps its object ids and scores 1.0; an unrelated project
    scores near zero and reaches only the label and name rules, which pair anything sharing an
    `Audio N`. That is the difference between applying a template and renaming someone's
    guitars to drum names, so it is measured rather than assumed.
    """
    return sum(p.rule == "object" for p in pairs) / len(pairs) if pairs else 0.0
