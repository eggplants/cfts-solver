""".. include:: ../README.md"""  # noqa: D415

from __future__ import annotations

import importlib.metadata

from .browser import (
    DEFAULT_SETTLE,
    DEFAULT_TIMEOUT,
    POLL_INTERVAL,
    BrowserResult,
    ChallengeBrowser,
    DrissionBrowser,
    find_turnstile_checkbox,
)
from .challenge import (
    BOT_COOKIE,
    CHALLENGE_STATUS_CODES,
    CLEARANCE_COOKIE,
    MITIGATION_HEADER,
    Challenge,
    ChallengeType,
    HeaderMapping,
    header_value,
    is_blocked,
    is_challenged,
    parse_challenge_page,
    parse_options,
    parse_sitekey,
)
from .clearance import (
    CHROME_HEADERS,
    DEFAULT_TTL,
    Clearance,
    ClearanceStore,
    default_store_path,
    store_key,
)
from .client import (
    DEFAULT_IMPERSONATE,
    ResponseLike,
    TurnstileSession,
    TurnstileSolver,
    domain_of,
    is_challenged_response,
    proxies_for,
    solve_challenge,
)
from .errors import (
    BlockedError,
    BrowserUnavailableError,
    ChallengePageError,
    ChallengeUnsolvedError,
    ClearanceExpiredError,
    TurnstileSolveError,
)

try:
    __version__ = importlib.metadata.version(__name__)
except importlib.metadata.PackageNotFoundError:  # pragma: no cover
    __version__ = "0.0.0"

__all__ = (
    "BOT_COOKIE",
    "CHALLENGE_STATUS_CODES",
    "CHROME_HEADERS",
    "CLEARANCE_COOKIE",
    "DEFAULT_IMPERSONATE",
    "DEFAULT_SETTLE",
    "DEFAULT_TIMEOUT",
    "DEFAULT_TTL",
    "MITIGATION_HEADER",
    "POLL_INTERVAL",
    "BlockedError",
    "BrowserResult",
    "BrowserUnavailableError",
    "Challenge",
    "ChallengeBrowser",
    "ChallengePageError",
    "ChallengeType",
    "ChallengeUnsolvedError",
    "Clearance",
    "ClearanceExpiredError",
    "ClearanceStore",
    "DrissionBrowser",
    "HeaderMapping",
    "ResponseLike",
    "TurnstileSession",
    "TurnstileSolveError",
    "TurnstileSolver",
    "__version__",
    "default_store_path",
    "domain_of",
    "find_turnstile_checkbox",
    "header_value",
    "is_blocked",
    "is_challenged",
    "is_challenged_response",
    "parse_challenge_page",
    "parse_options",
    "parse_sitekey",
    "proxies_for",
    "solve_challenge",
    "store_key",
)
