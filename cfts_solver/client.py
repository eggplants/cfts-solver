"""Driving the exchange end to end, then getting out of the browser's way.

The browser is a means, not the point: it runs once, earns a ``cf_clearance``
cookie, and hands it to a ``curl_cffi`` session that carries Chrome's TLS and
HTTP/2 fingerprints. Every request after that is plain HTTP at plain HTTP
speed, with no Chromium in the loop.

Three levels of interface, cheapest first:

* :func:`solve_challenge` -- one call, one clearance, do what you like with it.
* :class:`TurnstileSolver` -- reuse one browser and one cache for many hosts.
* :class:`TurnstileSession` -- a ``curl_cffi`` session that notices a challenge
  and clears it for you.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable
from urllib.parse import urlparse

from curl_cffi import requests

from .browser import DEFAULT_TIMEOUT, ChallengeBrowser, DrissionBrowser
from .challenge import (
    CHALLENGE_STATUS_CODES,
    CLEARANCE_COOKIE,
    HeaderMapping,
    header_value,
    is_challenged,
)
from .clearance import DEFAULT_TTL, Clearance, ClearanceStore

if TYPE_CHECKING:
    from datetime import timedelta

    from curl_cffi.requests import Response, Session
    from curl_cffi.requests.impersonate import BrowserTypeLiteral
    from curl_cffi.requests.session import HttpMethod, ProxySpec

logger = logging.getLogger(__name__)

#: The TLS fingerprint ``curl_cffi`` imitates. It has to agree with the browser
#: that cleared the challenge, or Cloudflare sees Chrome's cookie arriving over
#: somebody else's handshake.
DEFAULT_IMPERSONATE: BrowserTypeLiteral = "chrome"


def domain_of(url: str) -> str:
    """Pull the host out of a URL.

    Args:
        url (str): The URL.

    Returns:
        str: The hostname, without port or credentials.
    """
    return urlparse(url).hostname or ""


def proxies_for(proxy: str | None) -> ProxySpec | None:
    """Build the proxy mapping ``curl_cffi`` expects.

    Args:
        proxy (str | None): A proxy URL, if any.

    Returns:
        ProxySpec | None: The mapping, or None for a direct connection.
    """
    return {"http": proxy, "https": proxy} if proxy else None


@runtime_checkable
class ResponseLike(Protocol):
    """Enough of an HTTP response to tell a challenge from real content."""

    @property
    def status_code(self) -> int:
        """The HTTP status."""
        ...  # pragma: no cover - protocol declaration

    @property
    def headers(self) -> HeaderMapping:
        """The response headers."""
        ...  # pragma: no cover - protocol declaration

    @property
    def text(self) -> str:
        """The decoded body."""
        ...  # pragma: no cover - protocol declaration


def is_challenged_response(response: ResponseLike, *, streamed: bool = False) -> bool:
    """Report whether a ``curl_cffi`` response is a challenge, not real content.

    Reads the body only when it might plausibly be an interstitial -- an HTML
    body on a challenge status -- so a large download is not decoded for
    nothing, and a streamed response is never consumed.

    Args:
        response (ResponseLike): The response to inspect.
        streamed (bool): Whether the body is still being streamed, in which
            case only the headers are consulted.

    Returns:
        bool: True if Cloudflare intercepted the request.
    """
    if is_challenged(response.headers):
        return True
    if streamed:
        return False
    content_type = header_value(response.headers, "content-type")
    if "html" not in content_type.lower():
        return False
    if response.status_code not in CHALLENGE_STATUS_CODES and response.status_code != 200:  # noqa: PLR2004 - HTTP 200: some zones serve the interstitial with one
        return False
    return is_challenged(response.headers, response.text)


class TurnstileSolver:
    """Earns clearances for Cloudflare-protected hosts, and remembers them.

    Args:
        browser (ChallengeBrowser | None): The browser to clear challenges
            with. Defaults to :class:`~cfts_solver.DrissionBrowser`.
        store (ClearanceStore | None): Where to keep clearances between runs.
            Defaults to the on-disk store; pass
            ``ClearanceStore.in_memory()`` to keep nothing.
        ttl (timedelta): How long to trust a clearance before re-solving.
        timeout (float): Seconds to give the browser per challenge.
    """

    def __init__(
        self,
        browser: ChallengeBrowser | None = None,
        store: ClearanceStore | None = None,
        ttl: timedelta = DEFAULT_TTL,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        """Initialize the solver. No browser starts until something is solved."""
        self.browser: ChallengeBrowser = browser if browser is not None else DrissionBrowser()
        self.store = store if store is not None else ClearanceStore()
        self.ttl = ttl
        self.timeout = timeout

    def solve(
        self,
        url: str,
        *,
        proxy: str | None = None,
        refresh: bool = False,
    ) -> Clearance:
        """Get a clearance for a URL, from the cache or from a browser.

        Args:
            url (str): The protected URL.
            proxy (str | None): The proxy to route through, if any. A
                clearance is bound to the IP that earned it, so this is part
                of the cache key rather than an incidental detail.
            refresh (bool): Ignore any cached clearance and solve again.

        Returns:
            Clearance: The clearance, ready to :meth:`~Clearance.apply`.
        """
        domain = domain_of(url)
        if not refresh:
            cached = self.store.get(domain, proxy)
            if cached is not None:
                logger.debug("Reusing the cached clearance for %s", domain)
                return cached

        result = self.browser.clear(url, proxy=proxy, timeout=self.timeout)
        issued_at = datetime.now(UTC)
        clearance = Clearance(
            domain=domain,
            cookies=result.cookies,
            user_agent=result.user_agent,
            issued_at=issued_at,
            expires_at=issued_at + self.ttl,
        )

        # An unprotected page clears without a cf_clearance cookie. That is a
        # fine result to return and a bad one to cache: there is nothing in it
        # worth reusing, and caching it would mask the day the host turns
        # protection on.
        if CLEARANCE_COOKIE in clearance.cookies:
            self.store.save(clearance, proxy)
        else:
            logger.info("%s cleared without a %s cookie; not caching", domain, CLEARANCE_COOKIE)
        return clearance

    def invalidate(self, url: str, proxy: str | None = None) -> None:
        """Forget the clearance for a URL, for instance after a fresh 403.

        Args:
            url (str): The protected URL.
            proxy (str | None): The proxy it was earned through, if any.
        """
        self.store.invalidate(domain_of(url), proxy)

    def session(
        self,
        url: str,
        *,
        proxy: str | None = None,
        impersonate: BrowserTypeLiteral = DEFAULT_IMPERSONATE,
        **kwargs: Any,  # noqa: ANN401 - forwarded verbatim to curl_cffi
    ) -> Session:
        """Build a ``curl_cffi`` session already cleared for a URL.

        Args:
            url (str): The protected URL.
            proxy (str | None): The proxy to route through, if any.
            impersonate (BrowserTypeLiteral): The fingerprint to imitate.
            **kwargs (Any): Passed through to ``curl_cffi.requests.Session``.

        Returns:
            Session: A session carrying the clearance cookies and the user
                agent that earned them.
        """
        clearance = self.solve(url, proxy=proxy)
        session = requests.Session(
            impersonate=impersonate,
            proxies=proxies_for(proxy),
            **kwargs,
        )
        clearance.apply(session)
        return session


class TurnstileSession(requests.Session):
    """A ``curl_cffi`` session that clears Cloudflare challenges as it meets them.

    Requests go out as normal. When one comes back as an interstitial the
    session solves it, loads the clearance, and replays the request -- so the
    browser only ever runs on the requests that actually needed it.

    Args:
        solver (TurnstileSolver | None): The solver to use. Defaults to a
            fresh one with the on-disk cache.
        proxy (str | None): The proxy to route both the requests and the
            browser through.
        impersonate (BrowserTypeLiteral): The fingerprint to imitate.
        max_retries (int): How many times to clear and replay one request
            before handing the challenge back to the caller.
        **kwargs (Any): Passed through to ``curl_cffi.requests.Session``.
    """

    def __init__(
        self,
        solver: TurnstileSolver | None = None,
        *,
        proxy: str | None = None,
        impersonate: BrowserTypeLiteral = DEFAULT_IMPERSONATE,
        max_retries: int = 2,
        **kwargs: Any,  # noqa: ANN401 - forwarded verbatim to curl_cffi
    ) -> None:
        """Initialize the session. No browser starts until a challenge shows up."""
        super().__init__(impersonate=impersonate, proxies=proxies_for(proxy), **kwargs)
        self.solver = solver if solver is not None else TurnstileSolver()
        self.proxy = proxy
        self.max_retries = max_retries

    def request(  # type: ignore[override]
        self,
        method: HttpMethod,
        url: str,
        *args: Any,  # noqa: ANN401 - forwarded verbatim to curl_cffi
        **kwargs: Any,  # noqa: ANN401 - forwarded verbatim to curl_cffi
    ) -> Response:
        """Send a request, clearing a challenge and replaying it if one comes back.

        Args:
            method (HttpMethod): The HTTP method.
            url (str): The URL to request.
            *args (Any): Passed through to ``curl_cffi``.
            **kwargs (Any): Passed through to ``curl_cffi``.

        Returns:
            Response: The response, from the replay if a challenge was cleared.
        """
        streamed = bool(kwargs.get("stream"))
        response = super().request(method, url, *args, **kwargs)

        for attempt in range(self.max_retries):
            if not is_challenged_response(response, streamed=streamed):
                return response
            # The first attempt may still be holding a clearance that simply
            # had not been loaded yet; only after that is re-solving warranted.
            logger.info("Cloudflare challenged %s, clearing it (attempt %d)", url, attempt + 1)
            clearance = self.solver.solve(url, proxy=self.proxy, refresh=attempt > 0)
            clearance.apply(self)
            response = super().request(method, url, *args, **kwargs)

        return response


def solve_challenge(
    url: str,
    *,
    proxy: str | None = None,
    headless: bool = False,
    timeout: float = DEFAULT_TIMEOUT,
) -> Clearance:
    """Clear a Cloudflare challenge in one call.

    Args:
        url (str): The protected URL.
        proxy (str | None): The proxy to route through, if any.
        headless (bool): Run the browser without a window. Cloudflare grades
            headless Chrome harder; on a server, prefer ``xvfb``.
        timeout (float): Seconds to give the browser.

    Returns:
        Clearance: The clearance, ready to :meth:`~Clearance.apply`.
    """
    solver = TurnstileSolver(browser=DrissionBrowser(headless=headless), timeout=timeout)
    return solver.solve(url, proxy=proxy)


__all__ = (
    "DEFAULT_IMPERSONATE",
    "ResponseLike",
    "TurnstileSession",
    "TurnstileSolver",
    "domain_of",
    "is_challenged_response",
    "proxies_for",
    "solve_challenge",
)
