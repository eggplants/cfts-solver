from __future__ import annotations

import pytest

from cfts_solver.challenge import (
    CHALLENGE_STATUS_CODES,
    CLEARANCE_COOKIE,
    Challenge,
    is_blocked,
    is_challenged,
    parse_challenge_page,
    parse_options,
    parse_sitekey,
)
from cfts_solver.errors import ChallengePageError


def test_clearance_cookie_name():
    assert CLEARANCE_COOKIE == "cf_clearance"
    assert 403 in CHALLENGE_STATUS_CODES


def test_is_challenged_from_header():
    assert is_challenged({"cf-mitigated": "challenge"})
    assert is_challenged({"Cf-Mitigated": "Challenge"})


def test_is_challenged_ignores_other_mitigations():
    assert not is_challenged({"cf-mitigated": "block"})
    assert not is_challenged({})


def test_is_challenged_from_body(challenge_html):
    assert is_challenged({}, challenge_html)


def test_is_challenged_leaves_real_pages_alone(clean_html):
    # A legitimate footer printing a ray id must not read as a challenge.
    assert not is_challenged({}, clean_html)


def test_is_blocked(block_html, challenge_html):
    assert is_blocked(block_html)
    assert not is_blocked(challenge_html)


def test_parse_options(challenge_html):
    options = parse_options(challenge_html)
    assert options["cRay"] == "8f0a1b2c3d4e5f60"
    assert options["cType"] == "interactive"
    assert options["cZone"] == "example.com"
    assert options["cvId"] == "3"


def test_parse_options_unescapes_slashes(challenge_html):
    assert parse_options(challenge_html)["cUPMDTk"] == "/?__cf_chl_tk=deadbeef"


def test_parse_options_rejects_a_normal_page(clean_html):
    with pytest.raises(ChallengePageError):
        parse_options(clean_html)


def test_parse_options_rejects_an_unterminated_literal():
    with pytest.raises(ChallengePageError):
        parse_options("<script>window._cf_chl_opt={cRay: 'abc'</script>")


def test_parse_options_rejects_a_non_object():
    with pytest.raises(ChallengePageError):
        parse_options("<script>window._cf_chl_opt</script>")


def test_parse_options_stops_at_the_matching_brace():
    html = "window._cf_chl_opt={a: '1', b: {c: '2'}};window._cf_other={d: '3'}"
    options = parse_options(html)
    assert options["a"] == "1"
    assert "d" not in options


def test_parse_sitekey(challenge_html):
    assert parse_sitekey(challenge_html) == "0x4AAAAAAADnPIDROrmt1Wwj"


def test_parse_sitekey_from_a_render_call():
    assert parse_sitekey("turnstile.render('#c', {sitekey: '0xABC', theme: 'light'})") == "0xABC"


def test_parse_sitekey_missing(clean_html):
    assert parse_sitekey(clean_html) is None


def test_parse_challenge_page(challenge_html):
    challenge = parse_challenge_page(challenge_html)
    assert challenge.ray_id == "8f0a1b2c3d4e5f60"
    assert challenge.challenge_type == "interactive"
    assert challenge.zone == "example.com"
    assert challenge.sitekey == "0x4AAAAAAADnPIDROrmt1Wwj"
    assert challenge.is_interactive


def test_challenge_is_interactive_only_for_the_interactive_kind():
    assert not Challenge(ray_id="r", challenge_type="managed", zone="z").is_interactive


def test_parse_challenge_page_rejects_a_normal_page(clean_html):
    with pytest.raises(ChallengePageError):
        parse_challenge_page(clean_html)
