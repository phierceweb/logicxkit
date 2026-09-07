"""Skips for tests that need the untracked data root (`logicxkit.utils.data`)."""

import unittest

from logicxkit.utils.data import ENV, have_data


def needs(kind: str, *names: str):
    """Class decorator: skip unless the data root holds ``kind`` (and ``names`` in it)."""
    return unittest.skipUnless(have_data(kind, *names), f"no {kind} data under the data root ({ENV})")


def require(kind: str, *names: str) -> None:
    """Module-level: skip the whole file unless the data is there."""
    if not have_data(kind, *names):
        raise unittest.SkipTest(f"no {kind} data under the data root ({ENV})")
