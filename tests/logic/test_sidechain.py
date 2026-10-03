"""A slot's side-chain source: read, written, and carried between projects by name."""

import unittest

from _records import chan, env_obj, proj, rec, track, uuid
from logicxkit.logic.services.mixer.sidechain import SideChain, carry, resolve, side_chain, source_name, with_side_chain

HDR = 36


def slot(owner: int, key: int, source: tuple[int, int] | None = None, size: int = 400) -> bytes:
    p = bytearray(size)
    p[6] = key - 4
    if source:
        p[144], p[145] = source
    return rec(b"UCuA", owner, key, bytes(p), 5)


def session(kick_owner: int = 2, kick_label: str = "Audio 3", *, kick: bool = True, twice: bool = False) -> bytes:
    """Kick In on an audio channel, the Drums aux fed by Bus 1, Bus 2 bare, an instrument."""
    parts = [env_obj(88, "Kick In"), env_obj(212, "Drums"), env_obj(416, "Keys"),
             chan(12, "Bus 1", uuid=uuid(500)), chan(13, "Bus 2", uuid=uuid(501)),
             chan(68, "Aux 2", uuid=uuid(212), source=uuid(500)),
             chan(87, "Inst 3", uuid=uuid(416)), chan(5, "Audio 6", uuid=uuid(700)),
             track(1, 212), track(2, 416)]
    if kick:
        parts += [chan(kick_owner, kick_label, uuid=uuid(88)), track(0, 88)]
    if twice:
        parts += [env_obj(89, "Kick In"), chan(9, "Audio 10", uuid=uuid(89)), track(3, 89)]
    return proj(*parts)


class ReadWriteTest(unittest.TestCase):
    def test_none_bus_and_audio(self):
        self.assertIsNone(side_chain(bytes(200)))
        self.assertEqual(side_chain(slot(0, 4, (0x45, 1))[HDR:]), SideChain(0x45, 1))
        self.assertEqual(SideChain(0x45, 1).label, "Bus 2")
        self.assertEqual(SideChain(0x40, 0).label, "Audio 1")

    def test_written_and_cleared_in_place(self):
        raw = slot(0, 4)
        out = with_side_chain(raw, SideChain(0x40, 6))
        self.assertEqual(len(out), len(raw))
        self.assertEqual(side_chain(out[HDR:]), SideChain(0x40, 6))
        self.assertEqual(with_side_chain(out, None), raw)


class ResolveTest(unittest.TestCase):
    def test_a_track_by_name_or_label(self):
        data = session()
        self.assertEqual(resolve(data, "Kick In"), SideChain(0x40, 2))
        self.assertEqual(resolve(data, "kick in"), SideChain(0x40, 2))
        self.assertEqual(resolve(data, "Audio 3"), SideChain(0x40, 2))

    def test_a_bus_by_its_returns_name_or_number(self):
        data = session()
        self.assertEqual(resolve(data, "Drums"), SideChain(0x45, 0))
        self.assertEqual(resolve(data, "Bus 1"), SideChain(0x45, 0))
        self.assertEqual(resolve(data, "Bus 2"), SideChain(0x45, 1))

    def test_refusals(self):
        data = session(twice=True)
        with self.assertRaisesRegex(ValueError, "no channel named 'Snare'"):
            resolve(data, "Snare")
        self.assertEqual(resolve(data, "Keys"), SideChain(0x43, 2))           # an instrument track: Inst 3
        with self.assertRaisesRegex(ValueError, "several channels"):
            resolve(data, "Kick In")

    def test_an_object_whose_name_does_not_decode_does_not_stop_a_lookup(self):
        data = proj(env_obj(88, "Kick In"), env_obj(900, b"Gitarre \xfc"),
                    chan(2, "Audio 3", uuid=uuid(88)), chan(9, "Audio 10", uuid=uuid(900)),
                    track(0, 88), track(1, 900))
        self.assertEqual(resolve(data, "Kick In"), SideChain(0x40, 2))
        self.assertEqual(source_name(data, SideChain(0x40, 9)), "Audio 10")

    def test_source_names(self):
        data = session()
        self.assertEqual(source_name(data, SideChain(0x45, 0)), "Drums")
        self.assertEqual(source_name(data, SideChain(0x45, 1)), "Bus 2")
        self.assertEqual(source_name(data, SideChain(0x40, 2)), "Kick In")
        self.assertEqual(source_name(data, SideChain(0x40, 5)), "Audio 6")


class CarryTest(unittest.TestCase):
    def test_the_same_name_on_another_channel(self):
        src, dst = session(2, "Audio 3"), session(6, "Audio 7")
        raw = slot(2, 4, (0x40, 2))
        out, note = carry(src, raw, dst)
        self.assertEqual(side_chain(out[HDR:]), SideChain(0x40, 6))
        self.assertEqual(note, "side chain 'Kick In': Audio 3 -> Audio 7")

    def test_unchanged_when_the_numbers_agree(self):
        src = session()
        self.assertEqual(carry(src, slot(2, 4, (0x45, 0)), src), (slot(2, 4, (0x45, 0)), None))
        self.assertEqual(carry(src, slot(2, 4), src), (slot(2, 4), None))

    def test_cleared_with_a_note_when_the_name_is_absent(self):
        out, note = carry(session(), slot(2, 4, (0x40, 2)), session(kick=False))
        self.assertIsNone(side_chain(out[HDR:]))
        self.assertTrue(note.startswith("side chain 'Kick In' cleared: no channel named 'Kick In'"), note)


if __name__ == "__main__":
    unittest.main()
