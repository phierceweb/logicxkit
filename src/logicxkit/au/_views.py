"""Terminal rendering for au decode results (data assembly lives in services)."""

from __future__ import annotations


def _fmt_value(row: dict) -> str:
    if row.get("display"):
        return row["display"]
    unit = f" {row['unit']}" if row.get("unit") and row["unit"] != "generic" else ""
    return f"{row['value']:.4g}{unit}"


def _fmt_rows(params: list[dict], all_rows: bool) -> list[str]:
    rows = params if all_rows else [r for r in params if r.get("changed")]
    lines = []
    for r in rows:
        dflt = "" if r.get("default") is None else f"  (default {r['default']:.4g})"
        lines.append(f"  [{r['id']:>5}] {r['name']:<44} = {_fmt_value(r)}{dflt}")
    if not all_rows and len(rows) < len(params):
        lines.append(f"  … {len(params) - len(rows)} more at default (--all to show)")
    return lines


def _header(out: dict) -> str:
    plug = out["plugin"]
    comp = plug.get("component") or f"{plug['manufacturer']}/{plug['subtype']}"
    name = f"  preset {out['preset_name']!r}" if out.get("preset_name") else ""
    return f"{comp} ({plug['manufacturer']}/{plug['subtype']}){name}  [{out['decode_path']}]"


def format_preset(out: dict, all_rows: bool) -> str:
    lines = [_header(out)]
    if out.get("host_error"):
        lines.append(f"  ! AU host failed, static fallback: {out['host_error']}")
    if out.get("neural"):
        n = out["neural"]
        secs = ", ".join(f"{k}({len(v)})" for k, v in n.get("sections", {}).items())
        lines.append(f"  Neural DSP state [{n['format']}]: {secs}")
        lines.append("  (full knob detail: logicxkit logic neural)")
    if out.get("sonible"):
        s = out["sonible"]
        lines.append(f"  sonible protobuf fields (unnamed; plugin {s.get('plugin')!r}):")
        for k, v in s["fields"].items():
            if isinstance(v, dict):
                inner = "  ".join(f"{ik}={iv}" for ik, iv in v.items())
                lines.append(f"    msg {k}: {inner}")
            else:
                lines.append(f"    {k} = {v}")
    if out.get("tr5"):
        t = out["tr5"]
        lines.append(f"  TR5 chain (current preset: {t.get('current_preset')})")
        for snap in t["snapshots"]:
            active = [s for s in snap["slots"] if s.get("bypass") != "1"]
            lines.append(f"    snapshot {snap['snapshot']}: {len(active)} active module(s)")
            for s in active:
                params = "  ".join(f"{k}={v}" for k, v in list(s["params"].items())[:8])
                lines.append(f"      {s['slot']} [{(s.get('guid') or '?')[:8]}]  {params}")
    lines.extend(_fmt_rows(out.get("params", []), all_rows))
    if not out.get("params") and out.get("blobs"):
        blobs = ", ".join(f"{k} ({v}B)" for k, v in out["blobs"].items())
        lines.append(f"  opaque state blobs: {blobs}")
    return "\n".join(lines)


def format_strip(states: list[dict], all_rows: bool) -> str:
    if not states:
        return "no embedded 3rd-party AU states found"
    chunks = []
    for st in states:
        where = f"@{st.get('offset', '?')}"
        if st.get("channel"):
            where += f"  {st['channel']}"
        chunks.append(f"— {where}\n" + format_preset(st, all_rows))
    return "\n\n".join(chunks)
