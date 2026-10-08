"""`project`'s chain names a slot of Logic's own from its slot header: a headerless native
block by its type id, an instrument with no float block, the metronome's Klopfgeist left out."""

import struct
import unittest
from logicxkit.logic.services.project.project import (
    channel_chain,
)


class NativeTypeIdTest(unittest.TestCase):
    """A native slot with no plug-in name string in its window is named from its GAMETSPP type
    id, as `plugins` names it (ChromaVerb, SilverVerb, EnVerb and Echo on a built patch)."""

    def _channel(self, type_ids):
        from _records import chan, rec
        out = chan(282, "Audio 2")
        for k, type_id in enumerate(type_ids):
            slot = bytearray(432)
            slot[6] = k
            slot[184:192] = b"GAMETSPP"
            struct.pack_into("<I", slot, 192, type_id)
            out += rec(b"UCuA", 282, 4 + k, bytes(slot), 5)
        return out

    def test_a_nameless_native_slot_is_named_from_its_type_id(self):
        self.assertEqual(channel_chain(self._channel([287, 150, 166, 147])),
                         [("ChromaVerb", None), ("SilverVerb", None), ("EnVerb", None), ("Echo", None)])

    def test_an_unknown_type_id_is_still_an_insert(self):
        self.assertEqual(channel_chain(self._channel([236, 999])), [("Channel EQ", None), ("type 999", None)])

    def test_a_native_instrument_is_not_an_insert(self):
        self.assertEqual(channel_chain(self._channel([158, 236])), [("Channel EQ", None)])


class HeaderNamedChainTest(unittest.TestCase):
    """A slot of Logic's own is named from its header: an instrument with no float block and a
    type no table names are both in the chain."""

    def _slot(self, index: int, name: bytes, maker: bytes, word: int, code: bytes, *, flags: int = 0,
              type_id: int | None = None) -> bytes:
        slot = bytearray(432)
        struct.pack_into("<H", slot, 4, 1)
        slot[6] = index
        slot[120:120 + len(name)] = name
        slot[132:136], slot[140:144] = maker, code
        struct.pack_into("<I", slot, 136, word)
        slot[151] = flags
        if type_id is not None:
            slot[184:192] = b"GAMETSPP"
            struct.pack_into("<I", slot, 192, type_id)
        return bytes(slot)

    def _channel(self, *slots: bytes) -> bytes:
        from _records import chan, rec
        return chan(282, "Inst 2") + b"".join(rec(b"UCuA", 282, 2 + k, slot, 5) for k, slot in enumerate(slots))

    def test_a_sampler_family_instrument_heads_the_chain(self):
        kit = self._slot(0, b"Drum Kit", b"MELC", 0, b"LMNA", flags=8)
        glow = self._slot(1, b"ChromaGlow", b"GAME", 0, struct.pack("<I", 9321), type_id=9321)
        self.assertEqual(channel_chain(self._channel(kit, glow)), [("Drum Kit Designer", None), ("ChromaGlow", None)])

    def test_the_header_wins_over_a_plugin_name_in_the_preset_string(self):
        comp = bytearray(self._slot(0, b"Compressor", b"GAME", 0, struct.pack("<I", 154), type_id=154))
        comp[14:30] = b"Gain Staging.pst"
        self.assertEqual(channel_chain(self._channel(bytes(comp))), [("Compressor", "Gain Staging")])

    def test_the_clicks_klopfgeist_is_hidden_but_a_chosen_one_is_listed(self):
        """The metronome channel's instrument is no insert of the user's; Klopfgeist chosen on
        an instrument track is (`instrument-klopfgeist-logic`)."""
        click = self._slot(0, b"Klopfgeist", b"GAME", 0, struct.pack("<I", 158), flags=8, type_id=158)
        eq = self._slot(1, b"Channel EQ", b"GAME", 0, struct.pack("<I", 236), type_id=236)
        self.assertEqual(channel_chain(self._channel(click, eq), metronome=True), [("Channel EQ", None)])
        self.assertEqual(channel_chain(self._channel(click, eq)), [("Klopfgeist", None), ("Channel EQ", None)])


if __name__ == "__main__":
    unittest.main()
