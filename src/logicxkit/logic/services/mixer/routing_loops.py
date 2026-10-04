"""Feedback loops in a project's routing. A channel's output on a bus, or a send of its that is
not bypassed, reaches every aux in use that the bus feeds; a channel that reaches itself that way
is in a loop."""

from __future__ import annotations

from .binding import bound_objects, channels, input_labels, output_labels
from .sends import read_sends
from ..arrange.environment import channel_objects


def _back_to(start: int, hops) -> list[tuple[str, int]] | None:
    """The shortest way from ``start`` back to itself, as (bus taken, channel reached) steps."""
    paths, seen = [[("", start)]], {start}
    while paths:
        longer = []
        for path in paths:
            for bus, aux in hops(path[-1][1]):
                if aux == start:
                    return path + [(bus, aux)]
                if aux not in seen:
                    seen.add(aux)
                    longer.append(path + [(bus, aux)])
        paths = longer
    return None


def routing_loops(data: bytes) -> list[tuple[str, ...]]:
    """Each loop as the channels and buses along it, its first channel repeated last: the
    shortest loop through each channel, one per set of channels. A channel with a track reads
    ``name (label)``."""
    chans, outs, sends = channels(data), output_labels(data), read_sends(data)
    fed: dict[str, list[int]] = {}
    for owner, bus in input_labels(data).items():
        if bus and bus.startswith("Bus ") and chans[owner].in_use:
            fed.setdefault(bus, []).append(owner)

    def hops(owner: int) -> list[tuple[str, int]]:
        buses = [outs.get(owner)] + [f"Bus {s.bus}" for s in sends.get(owner, ()) if not s.bypassed]
        return [(bus, aux) for bus in buses for aux in fed.get(bus, ())]

    found: dict[frozenset, list[tuple[str, int]]] = {}
    for start in sorted({aux for auxes in fed.values() for aux in auxes}):
        path = _back_to(start, hops)
        if path:
            found.setdefault(frozenset(owner for _bus, owner in path), path)

    objects, bound = channel_objects(data), bound_objects(data)

    def told(owner: int) -> str:
        label = chans[owner].label
        name = objects[bound[owner]].name if owner in bound else None
        return f"{name} ({label})" if name and name != label else label

    return [tuple(part for bus, owner in path for part in (bus, told(owner)) if part) for path in found.values()]


def new_loops(before: bytes, after: bytes) -> list[tuple[str, ...]]:
    """The loops in ``after`` that ``before`` does not have."""
    had = set(routing_loops(before))
    return [loop for loop in routing_loops(after) if loop not in had]
