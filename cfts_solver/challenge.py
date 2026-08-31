"""Recognising a Cloudflare challenge, and reading what it says.

Cloudflare answers a request it does not trust with an interstitial rather than
the page you asked for: HTTP 403 (or 429/503), a ``cf-mitigated: challenge``
header on modern zones, and a stub carrying ``window._cf_chl_opt`` plus a
Turnstile widget. Everything in this module is pure -- it looks at bytes that
have already been fetched and never touches the network.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

from .errors import ChallengePageError

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

#: Cookie Cloudflare sets once a challenge is cleared, and checks afterwards.
CLEARANCE_COOKIE = "cf_clearance"

#: Bot-management cookie that rides along with the clearance.
BOT_COOKIE = "__cf_bm"

#: Header modern zones set when they intercept a request.
MITIGATION_HEADER = "cf-mitigated"

#: Statuses Cloudflare serves an interstitial with.
CHALLENGE_STATUS_CODES = frozenset({403, 429, 503})

#: The three flavours of challenge, as ``_cf_chl_opt.cType`` names them.
ChallengeType = Literal["managed", "interactive", "non-interactive"]

_CHL_OPT_MARKER = "window._cf_chl_opt"

# Any one of these in the body means an interstitial, not the real page.
_CHALLENGE_MARKERS = (
    _CHL_OPT_MARKER,
    "/cdn-cgi/challenge-platform/",
    "cf-turnstile-response",
    "<title>just a moment",
    "challenges.cloudflare.com/turnstile",
)

# Block-specific phrases. "cloudflare ray id" alone is NOT enough: plenty of
# legitimate pages print one in the footer.
_BLOCK_MARKERS = (
    "sorry, you have been blocked",
    "you have been blocked",
    "error 1020",
    "attention required! | cloudflare",
)

# _cf_chl_opt is a JavaScript object literal, not JSON: bare keys, single
# quotes, escaped slashes. Pull the pairs out rather than trying to eval it.
_PAIR_RE = re.compile(
    r"""([A-Za-z_$][\w$]*)\s*:\s*(?:'([^']*)'|"([^"]*)"|([^,}\s]+))""",
)

_SITEKEY_RE = re.compile(r"""data-sitekey\s*=\s*["']([^"']+)["']""")
_RENDER_SITEKEY_RE = re.compile(r"""sitekey\s*:\s*["']([^"']+)["']""")


@runtime_checkable
class HeaderMapping(Protocol):
    """Anything that can list its headers as name/value pairs.

    Every HTTP client spells its header container differently -- ``dict``,
    ``curl_cffi``'s ``Headers``, ``requests``' ``CaseInsensitiveDict`` -- and
    all of them can do this much.
    """

    def items(self) -> Iterable[tuple[str, str | None]]:
        """List the headers.

        Returns:
            Iterable[tuple[str, str | None]]: The name/value pairs.
        """
        ...  # pragma: no cover - protocol declaration


def header_value(headers: HeaderMapping, name: str) -> str:
    """Look a header up without caring how it was capitalised.

    Args:
        headers (HeaderMapping): The response headers.
        name (str): The header to find, lowercase.

    Returns:
        str: The value, or an empty string if the header is absent.
    """
    for key, value in headers.items():
        if key.lower() == name:
            return value or ""
    return ""


def is_challenged(headers: HeaderMapping, body: str = "") -> bool:
    """Report whether a response is a Cloudflare interstitial, not real content.

    The header alone settles it on zones that send ``cf-mitigated``; older ones
    only give themselves away in the body, so pass it when you have it.

    Args:
        headers (Mapping[str, str]): The response headers.
        body (str): The response body, if it has been read.

    Returns:
        bool: True if Cloudflare intercepted the request with a challenge.
    """
    if header_value(headers, MITIGATION_HEADER).strip().lower() == "challenge":
        return True
    lowered = body.lower()
    return any(marker in lowered for marker in _CHALLENGE_MARKERS)


def is_blocked(body: str) -> bool:
    """Report whether Cloudflare blocked the client outright.

    Args:
        body (str): The response body.

    Returns:
        bool: True if the body is a block page rather than a challenge.
    """
    lowered = body.lower()
    return any(marker in lowered for marker in _BLOCK_MARKERS)


def parse_options(html: str) -> dict[str, str]:
    """Extract the ``window._cf_chl_opt`` object from a challenge page.

    Args:
        html (str): The challenge page body.

    Raises:
        ChallengePageError: If the page carries no ``_cf_chl_opt`` object.

    Returns:
        dict[str, str]: The object's keys and their string values.
    """
    start = html.find(_CHL_OPT_MARKER)
    if start == -1:
        msg = "The page carries no window._cf_chl_opt object."
        raise ChallengePageError(msg)
    opening = html.find("{", start)
    if opening == -1:
        msg = "window._cf_chl_opt is not an object literal."
        raise ChallengePageError(msg)

    depth = 0
    for index in range(opening, len(html)):
        if html[index] == "{":
            depth += 1
        elif html[index] == "}":
            depth -= 1
            if depth == 0:
                return _parse_pairs(html[opening : index + 1])
    msg = "window._cf_chl_opt is not terminated."
    raise ChallengePageError(msg)


def _parse_pairs(literal: str) -> dict[str, str]:
    """Read ``key: value`` pairs out of a flat JavaScript object literal.

    Args:
        literal (str): The object literal, braces included.

    Returns:
        dict[str, str]: The pairs, with escaped slashes restored.
    """
    options: dict[str, str] = {}
    for match in _PAIR_RE.finditer(literal):
        key = match.group(1)
        value = next(group for group in match.groups()[1:] if group is not None)
        options[key] = value.replace("\\/", "/")
    return options


def parse_sitekey(html: str) -> str | None:
    """Find the Turnstile sitekey on a page, if it has a widget.

    Interstitials embed the widget themselves; a site that mounts Turnstile on
    its own form advertises the key in ``data-sitekey``.

    Args:
        html (str): The page body.

    Returns:
        str | None: The sitekey, or None if the page has no widget.
    """
    for pattern in (_SITEKEY_RE, _RENDER_SITEKEY_RE):
        match = pattern.search(html)
        if match:
            return match.group(1)
    return None


@dataclass(frozen=True)
class Challenge:
    """What a challenge page says about itself.

    Attributes:
        ray_id (str): The Cloudflare ray id, worth quoting in a bug report.
        challenge_type (str): ``managed``, ``interactive`` or
            ``non-interactive``. Only the interactive kind needs a click.
        zone (str): The zone the challenge was issued for.
        sitekey (str | None): The Turnstile sitekey, if the page carries one.
        options (Mapping[str, str]): The full ``_cf_chl_opt`` object.
    """

    ray_id: str
    challenge_type: str
    zone: str
    sitekey: str | None = None
    options: Mapping[str, str] = field(default_factory=dict)

    @property
    def is_interactive(self) -> bool:
        """Whether the challenge needs the Turnstile checkbox clicked.

        Returns:
            bool: True for interactive challenges.
        """
        return self.challenge_type == "interactive"


def parse_challenge_page(html: str) -> Challenge:
    """Read a Cloudflare interstitial.

    Args:
        html (str): The challenge page body.

    Raises:
        ChallengePageError: If the page is not a Cloudflare challenge page.

    Returns:
        Challenge: What the page says about itself.
    """
    options = parse_options(html)
    return Challenge(
        ray_id=options.get("cRay", ""),
        challenge_type=options.get("cType", ""),
        zone=options.get("cZone", ""),
        sitekey=parse_sitekey(html),
        options=options,
    )


__all__ = (
    "BOT_COOKIE",
    "CHALLENGE_STATUS_CODES",
    "CLEARANCE_COOKIE",
    "MITIGATION_HEADER",
    "Challenge",
    "ChallengeType",
    "HeaderMapping",
    "header_value",
    "is_blocked",
    "is_challenged",
    "parse_challenge_page",
    "parse_options",
    "parse_sitekey",
)
