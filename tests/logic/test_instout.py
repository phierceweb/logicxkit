"""An aux fed from an instrument's extra output: the 68-byte record under the aux, the
source id and kind on its channel. Synthetic here; the goldens are Logic's saves 82 and 83
and the template's three Drums MIDI auxes, checked when present."""

import struct
import unittest
from _records import chan, proj, rec, uuid
from logicxkit.logic.services.insert import HEADER, project_records
from logicxkit.logic.services.instout import (
    SIZE,
    bind_instrument_output,
    binding_key,
    next_source_id,
    read_instrument_outputs,
)


def pattern(index: int = 11, inst: int = 1, name: bytes = b"Addictive 13-14") -> bytes:
    p = bytearray(SIZE)
    struct.pack_into("<I", p, 0, 72)
    struct.pack_into("<I", p, 4, 4)
    p[15] = index
    struct.pack_into("<H", p, 22, inst)
    p[24:36] = b"Anlx" + b"umua" + b"2DAx"
    p[36:36 + len(name)] = name
    p[52:68] = bytes(range(16))
    return bytes(p)


def state(owner: int, key: int = 13) -> bytes:
    return rec(b"UCuA", owner, key, bytes(192), 5)


def session() -> bytes:
    return proj(chan(0, "Audio 1", uuid=uuid(88)), state(0),
                *(chan(256 + k, f"Input {k + 1}", size=201, in_use=False) for k in range(4)),
                chan(86, "Inst 2", uuid=uuid(96)), state(86),
                chan(67, "Aux 1", uuid=uuid(100)), state(67),
                chan(68, "Aux 2", uuid=uuid(104)), state(68))


class BindTest(unittest.TestCase):
    def test_the_record_lands_below_the_state_record_and_the_channel_points_at_it(self):
        out = bind_instrument_output(session(), 67, pattern=pattern(), instrument=2)
        got = read_instrument_outputs(out)
        self.assertEqual(list(got), [67])
        b = got[67]
        self.assertEqual((b.key, b.index, b.instrument, b.plugin, b.name), (12, 11, 2, "xlnA/aumu/xAD2", "Addictive 13-14"))
        self.assertEqual(b.source_id, 4)                            # four mono inputs: 0-3 taken
        self.assertNotEqual(b.raw[52:68], bytes(range(16)))          # a fresh UUID
        recs = project_records(out)
        i = next(k for k, r in enumerate(recs) if r.owner == 67 and r.tag == b"UCuA" and r.key == 12)
        self.assertEqual(recs[i - 1].tag, b"OCuA")
        chan_rec = next(r for r in recs if r.owner == 67 and r.tag == b"OCuA")
        self.assertEqual(chan_rec.raw[HEADER + 94:HEADER + 96], bytes([4, 1]))

    def test_source_ids_count_up_and_a_rebind_replaces(self):
        out = bind_instrument_output(session(), 67, pattern=pattern(), instrument=2)
        out = bind_instrument_output(out, 68, pattern=pattern(index=12, name=b"Addictive 15-16"), instrument=2)
        self.assertEqual([b.source_id for b in read_instrument_outputs(out).values()], [4, 5])
        self.assertEqual(next_source_id(out), 6)
        again = bind_instrument_output(out, 67, pattern=pattern(index=3, name=b"Addictive D 5"), instrument=2)
        self.assertEqual(read_instrument_outputs(again)[67].name, "Addictive D 5")
        self.assertEqual(sum(1 for r in project_records(again) if r.owner == 67 and r.tag == b"UCuA" and r.key == 12), 1)

    def test_the_key_follows_the_state_record_but_never_drops_below_twelve(self):
        self.assertEqual(binding_key(session()), 12)
        self.assertEqual(binding_key(proj(chan(0, "Audio 1"))), 12)
        moved = session().replace(state(67), rec(b"UCuA", 67, 15, bytes(192), 5))
        self.assertEqual(binding_key(moved), 12)                     # the lowest state key wins
        low = session().replace(state(0), rec(b"UCuA", 0, 12, bytes(192), 5))
        self.assertEqual(binding_key(low), 12)                       # 11 was dropped by Logic

    def test_unbind_takes_the_record_and_the_source_bytes_away(self):
        from logicxkit.logic.services.instout import unbind_instrument_output
        out = bind_instrument_output(session(), 67, pattern=pattern(), instrument=2)
        back = unbind_instrument_output(out, 67)
        self.assertEqual(read_instrument_outputs(back), {})
        chan_rec = next(r for r in project_records(back) if r.owner == 67 and r.tag == b"OCuA")
        self.assertEqual(chan_rec.raw[HEADER + 94:HEADER + 96], b"\xff\xff")
        self.assertEqual(unbind_instrument_output(back, 67), back)

    def test_unbind_clears_a_bus_returns_source_byte_too(self):
        from logicxkit.logic.services.instout import unbind_instrument_output
        data = session()
        recs = project_records(data)
        i = next(k for k, r in enumerate(recs) if r.owner == 68 and r.tag == b"OCuA")
        buf = bytearray(recs[i].raw)
        buf[HEADER + 94] = 21                                                # Bus 2's id, kind 0
        data = data[:24] + b"".join(bytes(buf) if k == i else r.raw for k, r in enumerate(recs))
        out = unbind_instrument_output(data, 68)
        chan_rec = next(r for r in project_records(out) if r.owner == 68 and r.tag == b"OCuA")
        self.assertEqual(chan_rec.raw[HEADER + 94:HEADER + 96], b"\xff\xff")

    def test_refusals(self):
        with self.assertRaises(ValueError):
            bind_instrument_output(session(), 67, pattern=bytes(SIZE), instrument=2)
        with self.assertRaises(ValueError):
            bind_instrument_output(session(), 67, pattern=pattern(), instrument=9)
        with self.assertRaises(ValueError):
            bind_instrument_output(session(), 999, pattern=pattern(), instrument=2)
