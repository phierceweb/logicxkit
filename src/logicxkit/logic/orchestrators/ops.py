"""The unit of an apply-template run: one op, its kind, and what became of it."""

from __future__ import annotations

from dataclasses import dataclass, field

KINDS = ("add", "stack", "member", "order", "rename", "colour", "icon", "hidden", "power",
         "width", "chains", "refs", "output", "input", "instout", "sends", "levels", "group", "return")
STRUCTURE = ("add", "stack", "member", "order")


@dataclass
class Op:
    kind: str
    target: str                       # the session row or channel, by name and label
    detail: str
    rule: str = ""
    status: str = "planned"           # planned | done | skipped | refused | failed
    note: str = ""
    args: dict = field(default_factory=dict)
    row: int | None = None            # the session row's object id, when the op is about one
    made: int | None = None           # the object id an add or stack op created

    def line(self) -> str:
        tag = f"[{self.status}]" if self.status != "planned" else ""
        note = f"  ({self.note})" if self.note else ""
        return f"{self.kind:7s} {self.target:28s} {self.detail}{note} {tag}".rstrip()


def _reason(e: Exception) -> str:
    """The first line of an error that says something: a gate's heading line names no problem."""
    lines = [ln.strip() for ln in str(e).splitlines() if ln.strip()]
    return next((ln for ln in lines if not ln.startswith("refusing")), lines[0] if lines else str(e))
