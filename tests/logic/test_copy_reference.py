"""A strip reference copied onto a channel that has none lands among that channel's records."""

import unittest

from _records import chan, proj, rec
from logicxkit.logic.services.stream import project_records
from logicxkit.logic.services.transplant import copy_reference


def ref(owner: int, key: int, name: str) -> bytes:
    p = bytearray(192)
    p[16:16 + len(name)] = name.encode()
    return rec(b"UCuA", owner, key, bytes(p), 5)


def stub() -> bytes:
    """A 14-byte owner-0 OCuA: a save carries one before Audio 1's channel record and a run of
    them near the end of the file."""
    return rec(b"OCuA", 0, 0xFFFF, bytes(14), 7)


class CopyReferenceTest(unittest.TestCase):
    def test_audio_1_takes_it_not_the_owner_0_stubs_past_every_channel(self):
        src = proj(chan(0, "Audio 1"), ref(0, 13, "Kick In.cst"))
        dst = proj(stub(), chan(0, "Audio 1"), rec(b"UCuA", 0, 10, bytes(200), 5),
                   chan(1, "Audio 2"), ref(1, 12, "Kick Out.cst"), stub(), stub())
        out = copy_reference(src, dst, src_owner=0, dst_owner=0)
        self.assertEqual([(r.tag, r.owner, r.key) for r in project_records(out)], [
            (b"OCuA", 0, 0xFFFF), (b"OCuA", 0, 0xFFFF), (b"UCuA", 0, 10), (b"UCuA", 0, 12),
            (b"OCuA", 1, 0xFFFF), (b"UCuA", 1, 12), (b"OCuA", 0, 0xFFFF), (b"OCuA", 0, 0xFFFF)])


if __name__ == "__main__":
    unittest.main()
