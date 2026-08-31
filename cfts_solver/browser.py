"""Clearing the challenge in a real browser.

Cloudflare's interstitial is obfuscated JavaScript that grades the environment
running it -- there is no arithmetic to reproduce offline, so something has to
execute it. This module drives a local Chromium through DrissionPage: it opens
the page, waits for the non-interactive challenges to settle on their own,
clicks the Turnstile checkbox for the interactive ones, and comes back with the
cookies and the user agent that earned them.

That is the only part of the library that needs a browser. Everything after it
-- every request you actually care about -- goes through ``curl_cffi``.

Bring your own driver by implementing :class:`ChallengeBrowser`; the solver only
ever calls :meth:`ChallengeBrowser.clear`.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from DrissionPage import ChromiumOptions, ChromiumPage

from .challenge import is_blocked, is_challenged
from .errors import BlockedError, BrowserUnavailableError, ChallengeUnsolvedError

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

logger = logging.getLogger(__name__)

#: How long to wait for the challenge scripts to load before believing a page
#: that looks unprotected. They are fetched after the document, so a page read
#: too early looks clean whether or not it is.
DEFAULT_SETTLE = 4.0

#: How long to give the whole exchange, including the settle.
DEFAULT_TIMEOUT = 45.0

#: How often to re-read the page while waiting for the challenge to clear.
POLL_INTERVAL = 1.0

# Chromium flags. The automation banner and the first-run dialogs are noise;
# the rest keeps a throwaway profile from tripping over a shared one.
_DEFAULT_ARGUMENTS = (
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-popup-blocking",
    "--disable-features=AutomationControlled",
)


@dataclass(frozen=True)
class BrowserResult:
    """What the browser came back with once the challenge cleared.

    Attributes:
        url (str): The URL the browser ended on, redirects followed.
        html (str): The page body.
        cookies (Mapping[str, str]): Every cookie the browser held.
        user_agent (str): The user agent it presented.
    """

    url: str
    html: str
    cookies: Mapping[str, str]
    user_agent: str


@runtime_checkable
class ChallengeBrowser(Protocol):
    """A browser that can clear a Cloudflare challenge."""

    def clear(
        self,
        url: str,
        *,
        proxy: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> BrowserResult:
        """Open a URL and come back once the challenge is gone.

        Args:
            url (str): The URL to clear.
            proxy (str | None): The proxy to route through, if any.
            timeout (float): Seconds to allow before giving up.

        Returns:
            BrowserResult: The cleared page, its cookies and its user agent.
        """
        ...  # pragma: no cover - protocol declaration


def find_turnstile_checkbox(page: Any) -> Any | None:  # noqa: ANN401 - DrissionPage ships no element type to annotate against
    """Locate the Turnstile checkbox, shadow roots and all.

    The interstitial hides a ``cf-turnstile-response`` input next to the widget
    and buries the real checkbox two shadow roots deep, so walk down from the
    input rather than guessing at a selector.

    Args:
        page (Any): The DrissionPage tab to search.

    Returns:
        Any | None: The checkbox element, or None if the widget is not up yet.
    """
    for element in page.eles("tag:input"):
        attrs = element.attrs
        if "turnstile" not in attrs.get("name", "") or attrs.get("type") != "hidden":
            continue
        try:
            wrapper = element.parent().shadow_root
            if not wrapper:
                continue
            body = wrapper.child()("tag:body")
            inner = body.shadow_root
            if not inner:
                continue
            return inner("tag:input")
        except Exception as err:  # noqa: BLE001 - the widget rebuilds itself mid-walk; a miss is not fatal
            logger.debug("Turnstile checkbox walk failed: %s", err)
    return None


class DrissionBrowser:
    """A :class:`ChallengeBrowser` backed by a local Chromium.

    Args:
        headless (bool): Run without a window. Cloudflare grades headless
            Chrome harder, so the default is a visible browser; on a server,
            run the visible one under ``xvfb`` rather than turning this on.
        browser_path (str | None): Path to the Chromium binary, when it is not
            somewhere DrissionPage looks.
        arguments (Sequence[str]): Extra Chromium flags, appended to the
            defaults.
        user_agent (str | None): Override the user agent. Whatever the browser
            ends up presenting is what the clearance is bound to.
        settle (float): Seconds to let the challenge scripts load before
            deciding a page is unprotected.
    """

    def __init__(
        self,
        *,
        headless: bool = False,
        browser_path: str | None = None,
        arguments: Sequence[str] = (),
        user_agent: str | None = None,
        settle: float = DEFAULT_SETTLE,
    ) -> None:
        """Initialize the browser driver. Chromium starts on the first clear."""
        self.headless = headless
        self.browser_path = browser_path
        self.arguments = tuple(arguments)
        self.user_agent = user_agent
        self.settle = settle

    def build_options(self, proxy: str | None = None) -> ChromiumOptions:
        """Assemble the Chromium options for one run.

        Args:
            proxy (str | None): The proxy to route through, if any.

        Returns:
            ChromiumOptions: The configured options.
        """
        options = ChromiumOptions()
        options.auto_port()
        options.headless(self.headless)
        for argument in (*_DEFAULT_ARGUMENTS, *self.arguments):
            options.set_argument(argument)
        if self.browser_path:
            options.set_browser_path(self.browser_path)
        if self.user_agent:
            options.set_user_agent(self.user_agent)
        if proxy:
            options.set_proxy(proxy)
        return options

    def open_page(self, proxy: str | None = None) -> ChromiumPage:
        """Launch Chromium.

        Args:
            proxy (str | None): The proxy to route through, if any.

        Raises:
            BrowserUnavailableError: If Chromium could not be started.

        Returns:
            ChromiumPage: The fresh tab.
        """
        try:
            return ChromiumPage(addr_or_opts=self.build_options(proxy))
        except Exception as err:
            msg = (
                f"Could not launch Chromium: {err}. Clearing a Cloudflare challenge "
                "needs a real browser -- install Google Chrome or Chromium, or pass "
                "browser_path to DrissionBrowser."
            )
            raise BrowserUnavailableError(msg) from err

    def clear(
        self,
        url: str,
        *,
        proxy: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> BrowserResult:
        """Open a URL and come back once the challenge is gone.

        Args:
            url (str): The URL to clear.
            proxy (str | None): The proxy to route through, if any.
            timeout (float): Seconds to allow before giving up.

        Raises:
            BlockedError: If Cloudflare blocked the client outright, which no
                amount of waiting will undo.
            ChallengeUnsolvedError: If the challenge was still up at the
                deadline.

        Returns:
            BrowserResult: The cleared page, its cookies and its user agent.
        """
        page = self.open_page(proxy)
        try:
            logger.info("Opening %s", url)
            page.get(url)
            time.sleep(self.settle)
            self._wait_until_cleared(page, url, timeout)
            return self._collect(page)
        finally:
            self._quit(page)

    def _wait_until_cleared(self, page: ChromiumPage, url: str, timeout: float) -> None:
        """Poll until the interstitial is gone, clicking the checkbox once.

        Args:
            page (ChromiumPage): The tab to watch.
            url (str): The URL being cleared, for error messages.
            timeout (float): Seconds to allow before giving up.

        Raises:
            BlockedError: If the page turned into a block page.
            ChallengeUnsolvedError: If the deadline passed with the challenge
                still up.
        """
        deadline = time.monotonic() + timeout
        clicked = False
        html = self._read_html(page)

        while True:
            # A failed read tells us nothing, so never read it as success: keep
            # polling until the page settles or the deadline passes.
            if html is not None:
                if is_blocked(html):
                    raise BlockedError(url)
                if not is_challenged({}, html):
                    logger.info("Challenge cleared for %s", url)
                    return
            if time.monotonic() >= deadline:
                raise ChallengeUnsolvedError(url, self._read_title(page))

            # Non-interactive challenges resolve on their own; the interactive
            # ones sit there until the checkbox is clicked exactly once.
            if not clicked:
                checkbox = find_turnstile_checkbox(page)
                if checkbox is not None:
                    logger.info("Clicking the Turnstile checkbox")
                    checkbox.click()
                    clicked = True

            time.sleep(POLL_INTERVAL)
            html = self._read_html(page)

    def _collect(self, page: ChromiumPage) -> BrowserResult:
        """Read the cleared page off the browser.

        Args:
            page (ChromiumPage): The tab to read.

        Returns:
            BrowserResult: The cleared page, its cookies and its user agent.
        """
        return BrowserResult(
            url=str(page.url),
            html=self._read_html(page) or "",
            cookies=_cookies_as_dict(page.cookies()),
            user_agent=str(page.user_agent),
        )

    @staticmethod
    def _read_html(page: ChromiumPage) -> str | None:
        """Read the page body.

        Args:
            page (ChromiumPage): The tab to read.

        Returns:
            str | None: The body, or None if it could not be read -- which is
                not the same as an empty page and must not be read as one.
        """
        try:
            return str(page.html)
        except Exception as err:  # noqa: BLE001 - a mid-navigation read fails; the next poll retries
            logger.debug("Could not read the page body: %s", err)
            return None

    @staticmethod
    def _read_title(page: ChromiumPage) -> str:
        """Read the page title for a diagnostic message.

        Args:
            page (ChromiumPage): The tab to read.

        Returns:
            str: The title, or an empty string if it could not be read.
        """
        try:
            return str(page.title)
        except Exception as err:  # noqa: BLE001 - diagnostics must never mask the real failure
            logger.debug("Could not read the page title: %s", err)
            return ""

    @staticmethod
    def _quit(page: ChromiumPage) -> None:
        """Close the browser, never leaking a process and never raising.

        Args:
            page (ChromiumPage): The tab to close.
        """
        try:
            page.quit()
        except Exception as err:  # noqa: BLE001 - a failed close must not replace the caller's result
            logger.warning("Could not close the browser: %s", err)


def _cookies_as_dict(cookies: Any) -> dict[str, str]:  # noqa: ANN401 - DrissionPage returns its own cookie collection
    """Normalise whatever DrissionPage hands back into a name/value mapping.

    Args:
        cookies (Any): The browser's cookies.

    Returns:
        dict[str, str]: The cookies by name.
    """
    as_dict = getattr(cookies, "as_dict", None)
    if callable(as_dict):
        return {str(name): str(value) for name, value in as_dict().items()}
    return {str(cookie["name"]): str(cookie["value"]) for cookie in cookies if "name" in cookie and "value" in cookie}


__all__ = (
    "DEFAULT_SETTLE",
    "DEFAULT_TIMEOUT",
    "POLL_INTERVAL",
    "BrowserResult",
    "ChallengeBrowser",
    "DrissionBrowser",
    "find_turnstile_checkbox",
)
