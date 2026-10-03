"""diff.py A B — changed ProjectData records (positional) and DisplayState keys between two saves."""
import plistlib
import sys
from pathlib import Path

from logicxkit.logic.services.stream.recdiff import diff_records, load_project_data
from logicxkit.logic.services.stream.stream import project_records


def alt(p: Path) -> Path:
    return sorted((p / "Alternatives").glob("*"))[0]


def walk(x, y, path=""):
    if isinstance(x, dict) and isinstance(y, dict):
        for k in sorted(set(x) | set(y)):
            if k not in x: print("  added  ", path + "/" + k, repr(y[k])[:70])
            elif k not in y: print("  removed", path + "/" + k)
            else: walk(x[k], y[k], path + "/" + k)
    elif isinstance(x, list) and isinstance(y, list) and len(x) == len(y):
        for i, (p, q) in enumerate(zip(x, y)): walk(p, q, f"{path}[{i}]")
    elif x != y:
        if isinstance(x, bytes) and isinstance(y, bytes) and len(x) == len(y):
            offs = [i for i in range(len(x)) if x[i] != y[i]]
            print(f"  changed {path} bytes {offs[:12]}{'…' if len(offs) > 12 else ''}: " +
                  " ".join(f"{x[i]:02x}->{y[i]:02x}" for i in offs[:8]))
        else:
            print("  changed", path, repr(x)[:50], "->", repr(y)[:50])


a, b = Path(sys.argv[1]), Path(sys.argv[2])
da, db = load_project_data(a), load_project_data(b)
ra, rb = project_records(da), project_records(db)
d = diff_records(da, db)
print(f"ProjectData: {len(d.changed)} changed, {len(d.added)} added, {len(d.removed)} removed, {d.same} same")
for c in d.changed:
    x, y = ra[c.index].raw, rb[c.index].raw
    offs = [o for o in c.offsets if o not in (14, 15)]
    if not offs:
        continue
    show = " ".join(f"+{o}:{x[o]:02x}->{y[o]:02x}" for o in offs[:10] if o < len(x) and o < len(y))
    print(f"  {c.tag.decode('latin-1')} #{c.index} owner {c.owner} key {c.key} size {c.size_a}: {len(offs)} bytes {show}")
for e in d.added: print("  added", e)
for e in d.removed: print("  removed", e)
print("DisplayState.plist:")
walk(plistlib.loads((alt(a) / "DisplayState.plist").read_bytes()), plistlib.loads((alt(b) / "DisplayState.plist").read_bytes()))
