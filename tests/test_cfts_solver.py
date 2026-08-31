from __future__ import annotations

import pytest

import cfts_solver
from cfts_solver import __version__


def test_version_is_available():
    assert __version__


@pytest.mark.parametrize("name", cfts_solver.__all__)
def test_everything_exported_exists(name):
    assert hasattr(cfts_solver, name)


def test_all_has_no_duplicates():
    assert len(set(cfts_solver.__all__)) == len(cfts_solver.__all__)
