from __future__ import annotations

from datetime import timedelta

import pytest
from curl_cffi import requests

from cfts_solver.browser import BrowserResult
from cfts_solver.clearance import Clearance, ClearanceStore
from cfts_solver.client import (
    DEFAULT_IMPERSONATE,
    TurnstileSession,
    TurnstileSolver,
    domain_of,
    is_challenged_response,
    proxies_for,
    solve_challenge,
)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/145.0.0.0"


class FakeBrowser:
    """A ChallengeBrowser that hands back a canned result and counts its runs."""

    def __init__(self, cookies=None, user_agent=USER_AGENT, html="<html>ok</html>"):
        self.cookies = {"cf_clearance": "abc", "__cf_bm": "bm"} if cookies is None else cookies
        self.user_agent = user_agent
        self.html = html
        self.runs = []

    def clear(self, url, *, proxy=None, timeout=45.0):
        self.runs.append((url, proxy, timeout))
        return BrowserResult(url=url, html=self.html, cookies=self.cookies, user_agent=self.user_agent)


class FakeResponse:
    def __init__(self, status_code=200, headers=None, text="<html>real page</html>"):
        self.status_code = status_code
        self.headers = headers if headers is not None else {"content-type": "text/html"}
        self.text = text


def make_solver(browser=None, **kwargs):
    return TurnstileSolver(browser=browser or FakeBrowser(), store=ClearanceStore.in_memory(), **kwargs)


def test_domain_of():
    assert domain_of("https://user:pw@example.com:8443/a/b?c=d") == "example.com"
    assert domain_of("not a url") == ""


def test_proxies_for():
    assert proxies_for(None) is None
    assert proxies_for("http://p:1") == {"http": "http://p:1", "https": "http://p:1"}


def test_default_impersonate_is_chrome():
    assert DEFAULT_IMPERSONATE == "chrome"


def test_is_challenged_response_from_the_header():
    assert is_challenged_response(FakeResponse(headers={"cf-mitigated": "challenge"}))


def test_is_challenged_response_from_the_body(challenge_html):
    response = FakeResponse(status_code=403, text=challenge_html)
    assert is_challenged_response(response)


def test_is_challenged_response_on_a_200(challenge_html):
    assert is_challenged_response(FakeResponse(status_code=200, text=challenge_html))


def test_is_challenged_response_leaves_real_pages_alone(clean_html):
    assert not is_challenged_response(FakeResponse(text=clean_html))


def test_is_challenged_response_skips_non_html(challenge_html):
    response = FakeResponse(status_code=403, headers={"content-type": "application/json"}, text=challenge_html)
    assert not is_challenged_response(response)


def test_is_challenged_response_skips_uninteresting_statuses(challenge_html):
    assert not is_challenged_response(FakeResponse(status_code=404, text=challenge_html))


def test_is_challenged_response_never_reads_a_streamed_body():
    class Streaming:
        def __init__(self):
            self.status_code = 403
            self.headers = {"content-type": "text/html"}

        @property
        def text(self):
            msg = "reading a streamed body would consume it"
            raise AssertionError(msg)

    assert not is_challenged_response(Streaming(), streamed=True)


def test_solve_returns_a_clearance():
    browser = FakeBrowser()
    clearance = make_solver(browser).solve("https://example.com/protected")

    assert isinstance(clearance, Clearance)
    assert clearance.domain == "example.com"
    assert clearance.token == "abc"
    assert clearance.user_agent == USER_AGENT
    assert browser.runs == [("https://example.com/protected", None, 45.0)]


def test_solve_honours_the_configured_timeout():
    browser = FakeBrowser()
    make_solver(browser, timeout=5.0).solve("https://example.com/")

    assert browser.runs[0][2] == 5.0


def test_solve_expires_the_clearance_after_the_ttl():
    solver = make_solver(ttl=timedelta(minutes=5))
    clearance = solver.solve("https://example.com/")

    assert clearance.expires_at - clearance.issued_at == timedelta(minutes=5)


def test_solve_reuses_a_cached_clearance():
    browser = FakeBrowser()
    solver = make_solver(browser)
    first = solver.solve("https://example.com/")
    second = solver.solve("https://example.com/other")

    assert first == second
    assert len(browser.runs) == 1


def test_solve_refresh_ignores_the_cache():
    browser = FakeBrowser()
    solver = make_solver(browser)
    solver.solve("https://example.com/")
    solver.solve("https://example.com/", refresh=True)

    assert len(browser.runs) == 2


def test_solve_keys_the_cache_on_the_proxy():
    browser = FakeBrowser()
    solver = make_solver(browser)
    solver.solve("https://example.com/")
    solver.solve("https://example.com/", proxy="http://p:1")

    assert [run[1] for run in browser.runs] == [None, "http://p:1"]


def test_solve_does_not_cache_an_unprotected_page():
    browser = FakeBrowser(cookies={"session": "s"})
    solver = make_solver(browser)
    clearance = solver.solve("https://example.com/")
    solver.solve("https://example.com/")

    assert clearance.token == ""
    assert len(browser.runs) == 2


def test_invalidate_forces_a_re_solve():
    browser = FakeBrowser()
    solver = make_solver(browser)
    solver.solve("https://example.com/")
    solver.invalidate("https://example.com/")
    solver.solve("https://example.com/")

    assert len(browser.runs) == 2


def test_session_comes_back_cleared():
    session = make_solver().session("https://example.com/")

    assert session.headers["user-agent"] == USER_AGENT
    assert session.cookies["cf_clearance"] == "abc"


def test_solve_challenge_one_shot(monkeypatch):
    browser = FakeBrowser()
    monkeypatch.setattr("cfts_solver.client.DrissionBrowser", lambda **_kwargs: browser)
    monkeypatch.setattr("cfts_solver.client.ClearanceStore", ClearanceStore.in_memory)

    clearance = solve_challenge("https://example.com/", headless=True)

    assert clearance.token == "abc"
    assert browser.runs == [("https://example.com/", None, 45.0)]


class RecordingSession:
    """Stands in for curl_cffi's Session.request, returning canned responses."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, *args, **kwargs):
        # Patched onto the class as a plain object, so it is never bound: no self.
        self.calls.append((method, url))
        return self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]


def make_session(monkeypatch, responses, browser=None, **kwargs):
    recorder = RecordingSession(responses)
    monkeypatch.setattr(requests.Session, "request", recorder)
    session = TurnstileSession(solver=make_solver(browser), **kwargs)
    return session, recorder


def test_session_passes_a_clean_response_straight_through(monkeypatch, clean_html):
    browser = FakeBrowser()
    session, recorder = make_session(monkeypatch, [FakeResponse(text=clean_html)], browser)

    response = session.get("https://example.com/")

    assert response.status_code == 200
    assert len(recorder.calls) == 1
    assert browser.runs == []


def test_session_clears_a_challenge_and_replays(monkeypatch, challenge_html, clean_html):
    browser = FakeBrowser()
    session, recorder = make_session(
        monkeypatch,
        [FakeResponse(status_code=403, text=challenge_html), FakeResponse(text=clean_html)],
        browser,
    )

    response = session.get("https://example.com/")

    assert response.status_code == 200
    assert recorder.calls == [("GET", "https://example.com/"), ("GET", "https://example.com/")]
    assert len(browser.runs) == 1
    assert session.headers["user-agent"] == USER_AGENT


def test_session_gives_up_after_max_retries(monkeypatch, challenge_html):
    browser = FakeBrowser()
    session, recorder = make_session(
        monkeypatch,
        [FakeResponse(status_code=403, text=challenge_html)],
        browser,
        max_retries=2,
    )

    response = session.get("https://example.com/")

    assert response.status_code == 403
    assert len(recorder.calls) == 3
    # The first clear may reuse a cached clearance; only the retry re-solves.
    assert len(browser.runs) == 2


def test_session_routes_the_browser_through_its_proxy(monkeypatch, challenge_html, clean_html):
    browser = FakeBrowser()
    session, _ = make_session(
        monkeypatch,
        [FakeResponse(status_code=403, text=challenge_html), FakeResponse(text=clean_html)],
        browser,
        proxy="http://p:1",
    )

    session.get("https://example.com/")

    assert browser.runs[0][1] == "http://p:1"


@pytest.mark.parametrize("method", ["get", "post", "head"])
def test_session_supports_the_usual_verbs(monkeypatch, clean_html, method):
    session, recorder = make_session(monkeypatch, [FakeResponse(text=clean_html)])

    getattr(session, method)("https://example.com/")

    assert recorder.calls[0][0] == method.upper()
