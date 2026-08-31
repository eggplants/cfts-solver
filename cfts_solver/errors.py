"""Exceptions raised by cfts_solver."""

from __future__ import annotations


class TurnstileSolveError(Exception):
    """Base class for every failure while clearing a Cloudflare challenge."""


class ChallengePageError(TurnstileSolveError):
    """Raised when a page does not look like a Cloudflare challenge page."""


class BrowserUnavailableError(TurnstileSolveError):
    """Raised when the stealth browser could not be launched.

    Clearing a challenge needs a real Chromium: Cloudflare hands the client
    obfuscated JavaScript and grades how the browser runs it, so there is no
    pure-Python path to a token.
    """


class ChallengeUnsolvedError(TurnstileSolveError):
    """Raised when the challenge was still up when the deadline passed.

    Args:
        url (str): The URL that stayed challenged.
        title (str): The page title when the deadline passed, for diagnostics.
    """

    def __init__(self, url: str, title: str = "") -> None:
        """Initialize the error."""
        self.url = url
        self.title = title
        suffix = f" (last title: {title!r})" if title else ""
        super().__init__(f"Cloudflare challenge at {url} was not cleared{suffix}")


class BlockedError(TurnstileSolveError):
    """Raised when Cloudflare blocked the client outright.

    A block is a firewall decision, not a challenge -- there is nothing to
    solve, so retrying with the same IP will not help.

    Args:
        url (str): The URL that was blocked.
    """

    def __init__(self, url: str) -> None:
        """Initialize the error."""
        self.url = url
        super().__init__(f"Cloudflare blocked the request to {url}")


class ClearanceExpiredError(TurnstileSolveError):
    """Raised when a stored clearance is used past its lifetime."""


__all__ = (
    "BlockedError",
    "BrowserUnavailableError",
    "ChallengePageError",
    "ChallengeUnsolvedError",
    "ClearanceExpiredError",
    "TurnstileSolveError",
)
