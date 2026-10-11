"""Synthetic sessions for the apply-template tests: a two-track session with a master, the same
routed by uuid, a Logic 11.2-style template routed by index words, and a strip-reference record."""

import struct

from _records import chan, count_record, env_obj, marker, proj, rec, track, uuid


def session(*, kick_colour=96, kick_fader=99, vox_name="Vox"):
    obj = bytearray(env_obj(88, "Kick In"))
    obj[36 + 155] = kick_colour
    vox = env_obj(504, vox_name)
    return proj(bytes(obj), vox, env_obj(80, "Master", grouping=True),
                chan(0, "Audio 1", uuid=uuid(88), fader=kick_fader),
                chan(19, "Audio 20", uuid=uuid(504)),
                chan(402, "Output 1-2", uuid=uuid(80), size=201),
                track(0, 88), track(1, 504), track(2, 80, flag=3), marker())


def routed_session() -> bytes:
    """Kick In from Input 1 and Vox from Input 2, both to Output 1-2, by uuid."""
    return proj(env_obj(88, "Kick In"), env_obj(504, "Vox"), env_obj(80, "Master", grouping=True),
                chan(0, "Audio 1", uuid=uuid(88), dest=uuid(80), source=uuid(601)),
                chan(19, "Audio 20", uuid=uuid(504), dest=uuid(80), source=uuid(602)),
                chan(256, "Input 1", uuid=uuid(601), size=201),
                chan(257, "Input 2", uuid=uuid(602), size=201),
                chan(258, "Input 3", uuid=uuid(603), size=201),
                chan(402, "Output 1-2", uuid=uuid(80), size=201),
                track(0, 88), track(1, 504), track(2, 80, flag=3), marker())


def word_routed_template(*, kick_input: int = 0, fmt: int = 2511) -> bytes:
    """The same rows as Logic 11.2 saves them: class-6 channels routed by index words."""
    data = bytearray(proj(
        count_record(1, [0, 0, 0, 0, 32], 1),
        env_obj(88, "Kick In", type_value=1760), env_obj(504, "Vox", type_value=1760),
        env_obj(80, "Master", grouping=True, type_value=1760),
        chan(0, "Audio 1", uuid=uuid(88), size=233, ver=6, words=(0, kick_input)),
        chan(19, "Audio 20", uuid=uuid(504), size=233, ver=6, words=(0, 1)),
        chan(402, "Output 1-2", uuid=uuid(80), size=233, ver=6),
        track(0, 88), track(1, 504), track(2, 80, flag=3), marker()))
    struct.pack_into("<H", data, 4, fmt)
    return bytes(data)


def ref(owner: int, name: str, category: str = "Guitar") -> bytes:
    """A channel's strip-reference record: the name and category fields a `.cst` reference holds."""
    return rec(b"UCuA", owner, 10, b"\x00" * 16 + name.encode().ljust(64, b"\x00") + category.encode().ljust(64, b"\x00"))
