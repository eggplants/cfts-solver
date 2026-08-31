from __future__ import annotations

import pytest

from cfts_solver.errors import (
    BlockedError,
    BrowserUnavailableError,
    ChallengePageError,
    ChallengeUnsolvedError,
    ClearanceExpiredError,
    TurnstileSolveError,
)


@pytest.mark.parametrize(
    "error",
    [
        ChallengePageError,
        BrowserUnavailableError,
        ChallengeUnsolvedError,
        BlockedError,
        ClearanceExpiredError,
    ],
)
def test_every_error_shares_one_base(error):
    assert issubclass(error, TurnstileSolveError)


def test_challenge_unsolved_carries_the_url_and_title():
    error = ChallengeUnsolvedError("https://example.com/", "Just a moment...")

    assert error.url == "https://example.com/"
    assert error.title == "Just a moment..."
    assert "Just a moment" in str(error)


def test_challenge_unsolved_without_a_title():
    error = ChallengeUnsolvedError("https://example.com/")

    assert error.title == ""
    assert str(error).endswith("was not cleared")


def test_blocked_carries_the_url():
    error = BlockedError("https://example.com/")

    assert error.url == "https://example.com/"
    assert "https://example.com/" in str(error)
