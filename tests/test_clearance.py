from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from curl_cffi import requests

from cfts_solver.clearance import (
    CHROME_HEADERS,
    Clearance,
    ClearanceStore,
    default_store_path,
    store_key,
)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/145.0.0.0"


def make_clearance(domain="example.com", token="abc123", ttl_minutes=29):
    now = datetime.now(UTC)
    return Clearance(
        domain=domain,
        cookies={"cf_clearance": token, "__cf_bm": "bm"},
        user_agent=USER_AGENT,
        issued_at=now,
        expires_at=now + timedelta(minutes=ttl_minutes),
    )


def test_token():
    assert make_clearance().token == "abc123"


def test_token_is_empty_without_the_cookie():
    clearance = Clearance(domain="example.com", cookies={}, user_agent=USER_AGENT)
    assert clearance.token == ""


def test_defaults_expire_in_the_future():
    clearance = Clearance(domain="example.com", cookies={}, user_agent=USER_AGENT)
    assert not clearance.is_expired


def test_is_expired():
    assert make_clearance(ttl_minutes=-1).is_expired


def test_as_headers_pins_the_user_agent():
    headers = make_clearance().as_headers()
    assert headers["user-agent"] == USER_AGENT
    assert headers["cookie"] == "cf_clearance=abc123; __cf_bm=bm"
    assert headers["accept-language"] == CHROME_HEADERS["accept-language"]


def test_apply_loads_a_curl_cffi_session():
    session = requests.Session()
    make_clearance().apply(session)
    assert session.headers["user-agent"] == USER_AGENT
    assert session.cookies["cf_clearance"] == "abc123"


def test_roundtrip():
    clearance = make_clearance()
    assert Clearance.from_dict(clearance.to_dict()) == clearance


def test_store_key():
    assert store_key("example.com") == "example.com|"
    assert store_key("example.com", "http://p:1") == "example.com|http://p:1"


def test_default_store_path_follows_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    assert default_store_path() == tmp_path / "cfts-solver" / "clearances.json"


def test_store_saves_and_reads_back(tmp_path):
    path = tmp_path / "nested" / "clearances.json"
    store = ClearanceStore(path)
    clearance = make_clearance()
    store.save(clearance)

    assert ClearanceStore(path).get("example.com") == clearance


def test_store_separates_proxies(tmp_path):
    store = ClearanceStore(tmp_path / "c.json")
    store.save(make_clearance(), proxy="http://p:1")

    assert store.get("example.com") is None
    assert store.get("example.com", "http://p:1") is not None


def test_store_drops_expired_entries_on_read(tmp_path):
    store = ClearanceStore(tmp_path / "c.json")
    store.save(make_clearance(ttl_minutes=-1))

    assert store.get("example.com") is None
    assert ClearanceStore(tmp_path / "c.json").get("example.com") is None


def test_store_invalidate(tmp_path):
    store = ClearanceStore(tmp_path / "c.json")
    store.save(make_clearance())
    store.invalidate("example.com")

    assert store.get("example.com") is None
    store.invalidate("example.com")  # a second time is a no-op, not an error


def test_store_purge_expired(tmp_path):
    store = ClearanceStore(tmp_path / "c.json")
    store.save(make_clearance("fresh.example"))
    store.save(make_clearance("stale.example", ttl_minutes=-1))

    assert store.purge_expired() == 1
    assert store.purge_expired() == 0
    assert store.get("fresh.example") is not None


def test_store_clear(tmp_path):
    store = ClearanceStore(tmp_path / "c.json")
    store.save(make_clearance())
    store.clear()

    assert store.get("example.com") is None


def test_store_survives_a_corrupt_file(tmp_path):
    path = tmp_path / "c.json"
    path.write_text("{not json", encoding="utf-8")

    assert ClearanceStore(path).get("example.com") is None


def test_store_survives_a_wrongly_shaped_file(tmp_path):
    path = tmp_path / "c.json"
    path.write_text('["a list, not a mapping"]', encoding="utf-8")

    assert ClearanceStore(path).get("example.com") is None


def test_store_skips_unreadable_entries_but_keeps_the_rest(tmp_path):
    path = tmp_path / "c.json"
    store = ClearanceStore(path)
    store.save(make_clearance())
    data = path.read_text(encoding="utf-8").replace('"example.com|"', '"broken|"', 1)
    path.write_text(data.replace('"user_agent"', '"nope"', 1), encoding="utf-8")

    assert ClearanceStore(path).get("broken") is None


def test_store_missing_file_is_not_an_error(tmp_path):
    assert ClearanceStore(tmp_path / "absent.json").get("example.com") is None


def test_in_memory_store_never_touches_the_disk(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    store = ClearanceStore.in_memory()
    store.save(make_clearance())

    assert store.path is None
    assert store.get("example.com") is not None
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    "mutate",
    [
        lambda store: store.invalidate("example.com"),
        lambda store: store.clear(),
        lambda store: store.purge_expired(),
    ],
)
def test_in_memory_store_write_paths_do_not_reach_the_disk(mutate):
    store = ClearanceStore.in_memory()
    store.save(make_clearance(ttl_minutes=-1))
    mutate(store)

    assert store.path is None
    assert store.get("example.com") is None


def test_store_leaves_no_temp_file_behind_when_the_write_fails(tmp_path, monkeypatch):
    store = ClearanceStore(tmp_path / "c.json")

    def fail(*_args, **_kwargs):
        msg = "disk full"
        raise OSError(msg)

    monkeypatch.setattr(Path, "replace", fail)

    with pytest.raises(OSError, match="disk full"):
        store.save(make_clearance())
    assert list(tmp_path.iterdir()) == []
