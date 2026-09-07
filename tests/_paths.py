"""Where the real-file goldens look for staged copies of the user's Logic files.

Every path here is an override with a neutral default, so the tests carry no personal
value and skip cleanly on any machine that lacks the files. Set the real ones in `.env`
(gitignored) — `bin/run` sources it.
"""

from pathlib import Path

from logicxkit.utils.env import env_path, env_str

REPO = Path(__file__).resolve().parent.parent

# Anchored to the repo, not the process cwd: a run started elsewhere would find no goldens at
# all and skip the whole layer green.
RESOURCES = env_path("LOGICXKIT_RESOURCES", REPO / "resources")

# Tests read only what is staged under resources/ — never Logic's live library.
STRIP_ROOT = env_path("LOGICXKIT_STRIP_ROOT", RESOURCES / "strips" / "Channel Strip Settings")
TEMPLATES = env_path("LOGICXKIT_TEMPLATES", RESOURCES / "templates")

# The rig configs live in the private knowledge-base repo, not in this one.
RIG_CONFIG = env_path("LOGICXKIT_RIG_CONFIG", "~/.config/logicxkit/rig")

# The X32 scene is the one file under ~/Music a test may read, so `_liveguard` exempts it.
SCENE = env_path("LOGICXKIT_SCENE", "~/Music/Behringer/x32/Scenes/scene.scn")


# The band's own folder and project names — nothing here identifies a rig by default.
STRIP_LIB = env_str("LOGICXKIT_STRIP_LIB", "Example Mixing")
TRACK_LIB = env_str("LOGICXKIT_TRACK_LIB", "Example Tracking")
PROJECT_PREFIX = env_str("LOGICXKIT_PROJECT_PREFIX", "Example")


def channel_strip(*parts: str) -> Path:
    """A saved channel strip under the mixing library."""
    return STRIP_ROOT / "Track" / STRIP_LIB / Path(*parts)


def project(name: str) -> Path:
    """A .logicx project template, e.g. project("Mix") -> '<prefix> - Mix.logicx'."""
    return TEMPLATES / f"{PROJECT_PREFIX} - {name}.logicx"


def have(*paths) -> bool:
    return all(Path(p).exists() for p in paths)




def logic_version(project: Path) -> tuple[int, ...]:
    """The Logic build that last saved a bundle, from its ProjectInformation.plist."""
    import plistlib
    import re
    info = project / "Resources/ProjectInformation.plist"
    if not info.exists():
        return ()
    m = re.search(r"(\d+(?:\.\d+)*)", plistlib.loads(info.read_bytes()).get("LastSavedFrom", ""))
    return tuple(int(x) for x in m.group(1).split(".")) if m else ()


def staged(name: str) -> Path:
    """A template re-saved from the current Logic, from ``resources/templates/``; the copy
    saved by the newest Logic wins, since the goldens need the record layout the sessions
    carry.

    Two copies saved by the *same* Logic build are a tie, and picking one by list order chose
    a golden baseline by accident — two differing 6.5 MB files once sat staged like that. So a
    tie is raised rather than resolved.
    """
    candidates = [RESOURCES / "templates" / f"{PROJECT_PREFIX} - {name}.logicx"]
    found = [c for c in candidates if c.exists()]
    if not found:
        return candidates[0]
    best = max(logic_version(c) for c in found)
    tied = [c for c in found if logic_version(c) == best]
    if len(tied) > 1 and len({c.read_bytes() if c.is_file() else _fingerprint(c) for c in tied}) > 1:
        raise RuntimeError(
            f"two different {name!r} templates are staged and both were saved by Logic "
            f"{'.'.join(map(str, best))}: " + ", ".join(str(c) for c in tied)
            + " — delete the superseded one; a golden baseline must not be picked by list order")
    return tied[0]


def _fingerprint(project: Path) -> bytes:
    """Enough of a bundle to tell two copies apart: every alternative's ProjectData."""
    return b"".join(p.read_bytes() for p in sorted(project.glob("Alternatives/*/ProjectData")))


def onto_staged_strips(config: dict) -> dict:
    """A rig config with its strip paths remapped onto the staged snapshot, so a test uses real
    chain values without reading the live library.

    An absolute donor path that is not under the live library cannot be rebased, and passing it
    through would read a file outside the repo that `_liveguard` does not cover.
    """
    from logicxkit.logic.services.library import DEFAULT as LIVE

    out = dict(config)
    out["strip_root"] = str(STRIP_ROOT)
    donors = {}
    for name, spec in (config.get("donors") or {}).items():
        spec = dict(spec)
        cst = Path(spec["cst"]).expanduser() if spec.get("cst") else None
        if cst is not None and cst.is_absolute():
            if not cst.is_relative_to(LIVE):
                raise ValueError(
                    f"donor {name!r} names {cst} — outside both the repo and the live library, "
                    "so it cannot be rebased onto the staged snapshot")
            spec["cst"] = str(STRIP_ROOT / cst.relative_to(LIVE))
        donors[name] = spec
    if donors:
        out["donors"] = donors
    return out


def resource(*parts: str) -> Path:
    """A file under ``resources/`` — reference material, never written."""
    return RESOURCES.joinpath(*parts)
