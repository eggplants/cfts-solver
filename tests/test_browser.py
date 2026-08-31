from __future__ import annotations

import pytest

from cfts_solver import browser as browser_module
from cfts_solver.browser import (
    BrowserResult,
    ChallengeBrowser,
    DrissionBrowser,
    _cookies_as_dict,
    find_turnstile_checkbox,
)
from cfts_solver.errors import (
    BlockedError,
    BrowserUnavailableError,
    ChallengeUnsolvedError,
)


class FakeCheckbox:
    def __init__(self):
        self.clicks = 0

    def click(self):
        self.clicks += 1


class FakeLocatable:
    """An element that resolves any locator to one fixed child."""

    def __init__(self, child):
        self._child = child

    def __call__(self, locator):
        return self._child


class FakeShadowRoot(FakeLocatable):
    def __init__(self, child, body=None):
        super().__init__(child)
        self._body = body

    def child(self):
        return FakeLocatable(self._body)


class FakeInput:
    def __init__(self, attrs, checkbox=None, *, broken=False, rootless=False, bodyless=False):
        self.attrs = attrs
        self._checkbox = checkbox
        self._broken = broken
        self._rootless = rootless
        self._bodyless = bodyless

    def parent(self):
        if self._broken:
            msg = "the widget rebuilt itself"
            raise RuntimeError(msg)
        if self._rootless:
            return type("Wrapper", (), {"shadow_root": None})()
        inner = None if self._bodyless else FakeShadowRoot(self._checkbox)
        body = type("Body", (), {"shadow_root": inner})()
        return type("Wrapper", (), {"shadow_root": FakeShadowRoot(None, body=body)})()


class FakePage:
    """Enough of a DrissionPage tab to drive the wait loop."""

    def __init__(self, pages, *, inputs=(), title="Just a moment..."):
        self._pages = list(pages)
        self._inputs = list(inputs)
        self._title = title
        self.url = "https://example.com/"
        self.user_agent = "Mozilla/5.0 Chrome/145.0.0.0"
        self.quit_calls = 0
        self.visited = []

    @property
    def html(self):
        return self._pages[0] if len(self._pages) == 1 else self._pages.pop(0)

    @property
    def title(self):
        return self._title

    def eles(self, locator):
        assert locator == "tag:input"
        return self._inputs

    def get(self, url):
        self.visited.append(url)

    def cookies(self):
        return [{"name": "cf_clearance", "value": "abc"}]

    def quit(self):
        self.quit_calls += 1


@pytest.fixture(autouse=True)
def _no_sleeping(monkeypatch):
    monkeypatch.setattr(browser_module.time, "sleep", lambda _seconds: None)


def test_drission_browser_satisfies_the_protocol():
    assert isinstance(DrissionBrowser(), ChallengeBrowser)


def test_find_turnstile_checkbox(challenge_html):
    checkbox = FakeCheckbox()
    page = FakePage(
        [challenge_html],
        inputs=[FakeInput({"name": "cf-turnstile-response", "type": "hidden"}, checkbox)],
    )
    assert find_turnstile_checkbox(page) is checkbox


def test_find_turnstile_checkbox_skips_unrelated_inputs():
    page = FakePage([""], inputs=[FakeInput({"name": "q", "type": "text"})])
    assert find_turnstile_checkbox(page) is None


def test_find_turnstile_checkbox_skips_visible_turnstile_inputs():
    page = FakePage([""], inputs=[FakeInput({"name": "cf-turnstile-response", "type": "text"})])
    assert find_turnstile_checkbox(page) is None


def test_find_turnstile_checkbox_survives_a_rebuilt_widget():
    page = FakePage(
        [""],
        inputs=[FakeInput({"name": "cf-turnstile-response", "type": "hidden"}, broken=True)],
    )
    assert find_turnstile_checkbox(page) is None


def test_find_turnstile_checkbox_without_a_shadow_root():
    element = FakeInput({"name": "cf-turnstile-response", "type": "hidden"}, rootless=True)
    assert find_turnstile_checkbox(FakePage([""], inputs=[element])) is None


def test_find_turnstile_checkbox_before_the_inner_root_is_attached():
    element = FakeInput({"name": "cf-turnstile-response", "type": "hidden"}, bodyless=True)
    assert find_turnstile_checkbox(FakePage([""], inputs=[element])) is None


class RecordingOptions:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def record(*args):
            self.calls.append((name, args))

        return record


def test_build_options_applies_every_setting(monkeypatch):
    recorded = RecordingOptions()
    monkeypatch.setattr(browser_module, "ChromiumOptions", lambda: recorded)

    DrissionBrowser(
        headless=True,
        browser_path="/usr/bin/chromium",
        arguments=("--mute-audio",),
        user_agent="UA",
    ).build_options("http://proxy:8080")

    names = [name for name, _ in recorded.calls]
    assert names.count("auto_port") == 1
    assert ("headless", (True,)) in recorded.calls
    assert ("set_browser_path", ("/usr/bin/chromium",)) in recorded.calls
    assert ("set_user_agent", ("UA",)) in recorded.calls
    assert ("set_proxy", ("http://proxy:8080",)) in recorded.calls
    assert ("set_argument", ("--mute-audio",)) in recorded.calls
    assert ("set_argument", ("--no-first-run",)) in recorded.calls


def test_build_options_leaves_out_what_was_not_asked_for(monkeypatch):
    recorded = RecordingOptions()
    monkeypatch.setattr(browser_module, "ChromiumOptions", lambda: recorded)

    DrissionBrowser().build_options()

    names = [name for name, _ in recorded.calls]
    assert "set_proxy" not in names
    assert "set_user_agent" not in names
    assert "set_browser_path" not in names
    assert ("headless", (False,)) in recorded.calls


def test_open_page_reports_a_missing_browser(monkeypatch):
    def explode(**_kwargs):
        msg = "no chrome here"
        raise OSError(msg)

    monkeypatch.setattr(browser_module, "ChromiumPage", explode)
    monkeypatch.setattr(DrissionBrowser, "build_options", lambda _self, _proxy=None: None)

    with pytest.raises(BrowserUnavailableError, match="Could not launch Chromium"):
        DrissionBrowser().open_page()


def test_clear_returns_once_the_challenge_is_gone(monkeypatch, challenge_html, clean_html):
    page = FakePage([challenge_html, clean_html, clean_html])
    monkeypatch.setattr(DrissionBrowser, "open_page", lambda _self, _proxy=None: page)

    result = DrissionBrowser(settle=0).clear("https://example.com/")

    assert isinstance(result, BrowserResult)
    assert result.cookies == {"cf_clearance": "abc"}
    assert result.user_agent == "Mozilla/5.0 Chrome/145.0.0.0"
    assert page.visited == ["https://example.com/"]
    assert page.quit_calls == 1


def test_clear_clicks_the_checkbox_exactly_once(monkeypatch, challenge_html, clean_html):
    checkbox = FakeCheckbox()
    page = FakePage(
        [challenge_html, challenge_html, clean_html, clean_html],
        inputs=[FakeInput({"name": "cf-turnstile-response", "type": "hidden"}, checkbox)],
    )
    monkeypatch.setattr(DrissionBrowser, "open_page", lambda _self, _proxy=None: page)

    DrissionBrowser(settle=0).clear("https://example.com/")

    assert checkbox.clicks == 1


def test_clear_raises_on_a_block_page(monkeypatch, block_html):
    page = FakePage([block_html])
    monkeypatch.setattr(DrissionBrowser, "open_page", lambda _self, _proxy=None: page)

    with pytest.raises(BlockedError):
        DrissionBrowser(settle=0).clear("https://example.com/")
    assert page.quit_calls == 1


def test_clear_gives_up_at_the_deadline(monkeypatch, challenge_html):
    page = FakePage([challenge_html])
    monkeypatch.setattr(DrissionBrowser, "open_page", lambda _self, _proxy=None: page)

    with pytest.raises(ChallengeUnsolvedError, match="Just a moment"):
        DrissionBrowser(settle=0).clear("https://example.com/", timeout=0)


def test_unreadable_pages_read_as_still_challenged(monkeypatch, challenge_html):
    class Unreadable(FakePage):
        @property
        def html(self):
            msg = "navigating"
            raise RuntimeError(msg)

        @property
        def title(self):
            msg = "navigating"
            raise RuntimeError(msg)

    page = Unreadable([challenge_html])
    monkeypatch.setattr(DrissionBrowser, "open_page", lambda _self, _proxy=None: page)

    with pytest.raises(ChallengeUnsolvedError):
        DrissionBrowser(settle=0).clear("https://example.com/", timeout=0)


def test_a_failed_close_is_swallowed(monkeypatch, clean_html):
    class Stubborn(FakePage):
        def quit(self):
            msg = "will not close"
            raise RuntimeError(msg)

    page = Stubborn([clean_html])
    monkeypatch.setattr(DrissionBrowser, "open_page", lambda _self, _proxy=None: page)

    assert DrissionBrowser(settle=0).clear("https://example.com/").url == "https://example.com/"


def test_cookies_as_dict_from_a_list():
    cookies = [{"name": "a", "value": "1"}, {"domain": "no name or value"}]
    assert _cookies_as_dict(cookies) == {"a": "1"}


def test_cookies_as_dict_from_a_drissionpage_collection():
    collection = type("CookiesList", (), {"as_dict": lambda _self: {"a": "1"}})()
    assert _cookies_as_dict(collection) == {"a": "1"}
