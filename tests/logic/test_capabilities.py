"""Every CLI subcommand declares what it is trusted for, and docs/CAPABILITIES.md's table is
generated from `_capabilities.py`; these tests fail when either drifts."""

import contextlib
import io
import re
import unittest
from pathlib import Path

import _paths  # noqa: F401

DOC = Path(__file__).resolve().parents[2] / "docs" / "CAPABILITIES.md"


def subcommands() -> set[str]:
    """The real parser's choices, read from its own usage line."""
    from logicxkit.logic.cli import main
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.suppress(SystemExit):
        main(["--help"])
    listed = re.search(r"\{([a-z,\-]+)\}", out.getvalue())
    return set(listed.group(1).split(",")) if listed else set()


class CapabilityRegistryTest(unittest.TestCase):
    def test_every_subcommand_is_declared(self):
        from logicxkit.logic._capabilities import by_command
        missing = subcommands() - set(by_command()) - {"capabilities"}
        self.assertEqual(missing, set(),
                         f"no confidence level declared in _capabilities.py for: {sorted(missing)}")

    def test_nothing_is_declared_that_the_cli_does_not_have(self):
        from logicxkit.logic._capabilities import by_command
        stale = set(by_command()) - subcommands()
        self.assertEqual(stale, set(), f"_capabilities.py rates absent commands: {sorted(stale)}")

    def test_no_command_is_declared_twice(self):
        from logicxkit.logic._capabilities import CAPABILITIES
        names = [n for cap in CAPABILITIES for n in cap.commands]
        self.assertEqual(sorted(names), sorted(set(names)), "a command is rated twice")

    def test_every_level_is_one_of_the_defined_ones(self):
        from logicxkit.logic._capabilities import CAPABILITIES, LEVELS
        for cap in CAPABILITIES:
            with self.subTest(cap.commands[0]):
                self.assertIn(cap.level, LEVELS)

    def test_a_claim_that_is_not_confirmed_says_why(self):
        """Anything short of CONFIRMED must name what is missing, or the row is not actionable."""
        from logicxkit.logic._capabilities import CAPABILITIES
        for cap in CAPABILITIES:
            if cap.level in ("CLAIMED", "DERIVED", "BROKEN"):
                with self.subTest(cap.commands[0]):
                    self.assertTrue(cap.catch or cap.safe,
                                    f"{cap.commands} is {cap.level} with nothing said about why")


class DocMatchesCodeTest(unittest.TestCase):
    def test_the_doc_carries_the_generated_table(self):
        from logicxkit.logic._capabilities import table
        self.assertIn(table(), DOC.read_text(),
                      "docs/CAPABILITIES.md is stale — regenerate it from _capabilities.py")

    def test_the_doc_points_at_the_source_of_truth(self):
        self.assertIn("generated from src/logicxkit/logic/_capabilities.py", DOC.read_text())


if __name__ == "__main__":
    unittest.main()


def test_notice_only_for_unconfirmed_levels():
    from logicxkit.logic._capabilities import CAPABILITIES, notice
    for cap in CAPABILITIES:
        for name in cap.commands:
            line = notice(name)
            if cap.level in ("CLAIMED", "DERIVED", "BROKEN"):
                assert line and cap.level in line, name
            else:
                assert line is None, name


def test_emit_notice_writes_only_on_a_write(capsys, monkeypatch):
    from argparse import Namespace

    from logicxkit.logic._capabilities import NOTICE_ENV, emit_notice

    monkeypatch.delenv(NOTICE_ENV, raising=False)
    emit_notice(Namespace(cmd="transplant", out=None))
    assert capsys.readouterr().err == ""

    emit_notice(Namespace(cmd="transplant", out="somewhere"))
    assert "transplant" in capsys.readouterr().err

    monkeypatch.setenv(NOTICE_ENV, "1")
    emit_notice(Namespace(cmd="transplant", out="somewhere"))
    assert capsys.readouterr().err == ""


def test_shipped_examples_do_not_target_the_live_library(monkeypatch):
    """Runs against the real default on purpose: an override makes this pass for free."""
    import json
    from pathlib import Path

    from logicxkit.logic.services.library import under_live_library
    from logicxkit.logic.services.pst import output_root
    from logicxkit.logic.services.spec import load_spec

    root = Path(__file__).resolve().parents[2] / "config"
    monkeypatch.delenv("LOGICXKIT_STRIP_ROOT", raising=False)
    monkeypatch.delenv("LOGICXKIT_AUDIO_MUSIC_APPS", raising=False)
    strips = load_spec(root / "example-strips.json")["_output_dir"]
    psts = output_root(json.loads((root / "example-psts.json").read_text()))
    assert not under_live_library(strips), strips
    assert not under_live_library(psts), psts


def test_live_library_write_is_refused_without_install(tmp_path, monkeypatch, capsys):
    """A spec that omits its output root must stop the run, not write to Logic's library."""
    import json

    from logicxkit.logic.cli import main
    from logicxkit.logic.services.library import USER_DATA_DEFAULT

    monkeypatch.delenv("LOGICXKIT_AUDIO_MUSIC_APPS", raising=False)
    target = USER_DATA_DEFAULT / "Plug-In Settings"
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({
        "output_dir": "Plug-In Settings",
        "presets": {"zz-logicxkit-test": {"eq": {"peak1": {"freq": 100, "gain": 3.0, "q": 1.0}}}},
    }))

    assert main(["pst", str(spec)]) == 2
    assert "refusing to write" in capsys.readouterr().err
    assert not (target / "Channel EQ/zz-logicxkit-test.pst").exists(), "the refusal did not hold"


def test_an_override_does_not_unguard_the_real_library(tmp_path, monkeypatch):
    from logicxkit.logic.services import library

    live, override = tmp_path / "live", tmp_path / "override"
    monkeypatch.setattr(library, "USER_DATA_DEFAULT", live)
    monkeypatch.setenv("LOGICXKIT_AUDIO_MUSIC_APPS", str(override))
    assert library.under_live_library(live / "Plug-In Settings/Channel EQ/x.pst")
    assert library.under_live_library(override / "Plug-In Settings/Channel EQ/x.pst")
    assert not library.under_live_library(tmp_path / "elsewhere/x.pst")


def test_pst_into_the_real_library_is_refused_with_an_override_set(tmp_path, monkeypatch):
    import json

    from logicxkit.logic.cli import main
    from logicxkit.logic.services import library

    live = tmp_path / "live"
    monkeypatch.setattr(library, "USER_DATA_DEFAULT", live)
    monkeypatch.setenv("LOGICXKIT_AUDIO_MUSIC_APPS", str(tmp_path / "override"))
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({
        "output_dir": str(live / "Plug-In Settings"),
        "presets": {"zz-logicxkit-test": {"eq": {"peak1": {"freq": 100, "gain": 3.0, "q": 1.0}}}},
    }))
    assert main(["pst", str(spec)]) == 2
    assert not (live / "Plug-In Settings/Channel EQ/zz-logicxkit-test.pst").exists()


def test_pst_exits_nonzero_when_a_preset_fails(tmp_path, monkeypatch, capsys):
    import json

    from logicxkit.logic.cli import main

    monkeypatch.setenv("LOGICXKIT_LOGIC_APP", str(tmp_path / "No Logic.app"))
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({
        "output_dir": str(tmp_path / "out"),
        "presets": {"zz": {"eq": {"peak1": {"freq": 100, "gain": 3.0, "q": 1.0}}}},
    }))
    assert main(["pst", str(spec)]) == 1
    assert "!!" in capsys.readouterr().out
