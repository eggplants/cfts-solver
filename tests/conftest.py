from __future__ import annotations

import pytest

CHALLENGE_HTML = """<!DOCTYPE html>
<html><head><title>Just a moment...</title></head>
<body>
  <div class="main-wrapper">
    <div id="challenge-stage">
      <div class="cf-turnstile" data-sitekey="0x4AAAAAAADnPIDROrmt1Wwj"></div>
      <input type="hidden" name="cf-turnstile-response">
    </div>
  </div>
  <script>window._cf_chl_opt={cvId: '3',cZone: "example.com",cType: 'interactive',
    cNounce: '12345',cRay: '8f0a1b2c3d4e5f60',cHash: 'abcdef',
    cUPMDTk: "\\/?__cf_chl_tk=deadbeef",cFPWv: 'b',cITimeS: '1700000000'};</script>
  <script src="/cdn-cgi/challenge-platform/h/b/orchestrate/chl_page/v1"></script>
</body></html>
"""

BLOCK_HTML = """<!DOCTYPE html>
<html><head><title>Attention Required! | Cloudflare</title></head>
<body><h1>Sorry, you have been blocked</h1><p>Error 1020</p></body></html>
"""

CLEAN_HTML = """<!DOCTYPE html>
<html><head><title>Example Domain</title></head>
<body><h1>Example Domain</h1><p>Cloudflare Ray ID: 8f0a1b2c3d4e5f60</p></body></html>
"""


@pytest.fixture
def challenge_html():
    return CHALLENGE_HTML


@pytest.fixture
def block_html():
    return BLOCK_HTML


@pytest.fixture
def clean_html():
    return CLEAN_HTML
