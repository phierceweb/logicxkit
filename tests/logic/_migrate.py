"""Fixtures for the `logic migrate` tests: a session of another lineage built from
test_stack_create's records, bundles and alternatives on disk, and the `Run` case that drives the
command in-process."""

import contextlib
import io
import plistlib
import shutil
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

from _records import chan, count_record, env_obj, gnos, index_entry, marker, proj, send, seq_triple, track, uuid
from test_stack_create import MIXER, TRACKS, sub

from logicxkit.logic._migrate_cmd import cmd_migrate
from logicxkit.logic.services.arrange.stacks import read_tracks

SYNTHETIC_SKIP = "modes,metronome"          # the synthetic records carry no song record to copy them from


def session(rename: dict[str, str] | None = None, shift: int = 0) -> bytes:
    """test_stack_create's session, with tracks renamed and every Environment object id moved
    by ``shift`` — a project of another lineage with the same layout."""
    rename = rename or {}

    def n(name):
        return rename.get(name, name)

    def i(oid):
        return oid + shift
    table = b"".join(index_entry(i(oid), 2 + k, 20 + 4 * k) for k, oid in enumerate(MIXER))
    return proj(
        count_record(12, [6, 0, 2, 1, 1, 0, 3], 12),
        gnos(*sorted(i(o) for o in (88, 92, 152, 192, 196, 212, 216, 504))),
        env_obj(i(192), n("Drums"), grouping=True), env_obj(i(88), n("Kick In")), env_obj(i(92), n("Snare Up")),
        env_obj(i(196), n("Bass"), grouping=True), env_obj(i(152), n("Bass DI")),
        env_obj(i(504), n("Test Bounce")), env_obj(i(212), n("Drums")), env_obj(i(216), n("Cymbals")),
        env_obj(i(80), n("Master"), grouping=True),
        chan(0, "Audio 1", uuid=uuid(i(88)), stack_index=1), chan(2, "Audio 3", uuid=uuid(i(92)), stack_index=1),
        chan(16, "Audio 17", uuid=uuid(i(152)), stack_index=2),
        chan(68, "Aux 2", uuid=uuid(i(212))), chan(69, "Aux 3", uuid=uuid(i(216))), chan(88, "Inst 4", uuid=uuid(i(504))),
        sub(379, 1, uuid=uuid(i(192))), sub(380, 2, uuid=uuid(i(196))),
        chan(381, "Input 1-2", size=201, in_use=False),
        chan(382, "Output 1-2", uuid=uuid(i(80)), size=201), send(382, 0, 5),
        seq_triple(1, big=table),
        track(0, i(192)), track(1, i(88), member=True), track(2, i(92), member=True), track(3, i(196)),
        track(4, i(152), member=True), track(5, i(504)), track(6, i(212)), track(7, i(216)),
        track(8, i(80), flag=3), marker(),
        *(track(k, oid) for k, oid in enumerate([296, 300, 304] + [i(o) for o in MIXER])), marker(),
        *(seq_triple(2 + k, slot=20 + 4 * k, object_id=i(oid), index=2 + k) for k, oid in enumerate(MIXER)),
        seq_triple(11, slot=100, size=341))


def other_lineage() -> bytes:
    return session({"Test Bounce": "Bounce"}, shift=1000)


def bundle(parent: Path, name: str, data: bytes, tracks: int = TRACKS) -> Path:
    return alternative(parent / f"{name}.logicx", "000", data, tracks)


def alternative(project: Path, name: str, data: bytes, tracks: int = TRACKS) -> Path:
    alt = project / "Alternatives" / name
    alt.mkdir(parents=True)
    (alt / "ProjectData").write_bytes(data)
    (alt / "MetaData.plist").write_bytes(plistlib.dumps({"NumberOfTracks": tracks}))
    return project


def names(project: Path) -> list[str]:
    return [r["name"] for r in read_tracks((project / "Alternatives/000/ProjectData").read_bytes(), TRACKS)]


def map_text(song: bytes, lines: list[str]) -> str:
    """Every session row mapped to the template row of the same name, then ``lines``."""
    keys = [f"{r['name']} ({r['label']})" for r in read_tracks(song, TRACKS)]
    return "\n".join([f"{k} -> {k}" for k in keys if k != "Bounce (Inst 4)"] + lines) + "\n"


class Run(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.tmpl = bundle(self.tmp / "t", "Tmpl", session())
        self.out = self.tmp / "out"

    def run_cli(self, song: Path, **kw) -> tuple[int, str]:
        args = Namespace(project=str(song), template=str(self.tmpl), out=str(self.out), map=None,
                         save_map=None, skip=SYNTHETIC_SKIP, force=False, verify=False)
        for k, v in kw.items():
            setattr(args, k, str(v) if isinstance(v, Path) else v)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cmd_migrate(args)
        return rc, buf.getvalue()

    def assert_nothing_written(self):
        self.assertFalse(self.out.exists(), sorted(self.out.rglob("*")) if self.out.exists() else None)
