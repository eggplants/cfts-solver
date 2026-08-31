# Cloudflare Turnstile Solver

[![PyPI](
  <https://img.shields.io/pypi/v/cfts-solver?color=blue>
  )](
  <https://pypi.org/project/cfts-solver/>
) [![CI](
  <https://github.com/eggplants/cfts-solver/actions/workflows/ci.yml/badge.svg>
  )](
  <https://github.com/eggplants/cfts-solver/actions/workflows/ci.yml>
)

Get past a [Cloudflare Turnstile](https://www.cloudflare.com/products/turnstile/) challenge once, then scrape with `curl_cffi`.

_Note: intended for accessing sites you are allowed to access programmatically._

## Installation

```bash
# uv
uv add cfts-solver

# pip
pip install cfts-solver
```

You also need Google Chrome or Chromium on the host. It runs once per host, to
clear the challenge; every request after that is plain HTTP.

## Use

```python
import cfts_solver
from curl_cffi import requests

URL = "https://example.com/"

session = requests.Session(impersonate="chrome")
res = session.get(URL)

if cfts_solver.is_challenged(res.headers, res.text):
    clearance = cfts_solver.solve_challenge(URL)
    clearance.apply(session)  # cookies plus the user agent that earned them
    res = session.get(URL)

print(res.status_code, len(res.text))
```

```python
from cfts_solver import TurnstileSession

with TurnstileSession() as session:
    res = session.get("https://example.com/")
    print(res.status_code)
```

```python
from cfts_solver import TurnstileSolver

solver = TurnstileSolver()
clearance = solver.solve("https://example.com/")
refreshed = solver.solve("https://example.com/", refresh=True)

print(clearance.token, clearance.user_agent)
```

Clearances are cached under `$XDG_CACHE_HOME/cfts-solver/`, keyed by host
and proxy, so a second process does not start a second browser. Pass
`ClearanceStore.in_memory()` to keep nothing, or `ClearanceStore(path)` to keep
it somewhere else.

<!--

## How it works

Cloudflare's interstitial is obfuscated JavaScript that grades the environment
running it, so unlike a proof-of-work challenge there is nothing to reproduce
offline -- something has to execute it. A browser does that once and comes back
with a `cf_clearance` cookie.

The cookie alone is not enough. It is bound to the user agent that earned it
and to the TLS fingerprint it arrived over, so this library keeps all three
together: the cookies, the exact user agent, and `curl_cffi`'s Chrome
impersonation. Send the cookie from `requests` and Cloudflare challenges you
again.

| Module | What it does |
| --- | --- |
| `challenge` | Spots an interstitial, reads `_cf_chl_opt`. No network. |
| `browser` | Drives Chromium, clicks the checkbox, takes the cookies. |
| `clearance` | Keeps the cookie and user agent together, on disk. |
| `client` | The solver, the clearing session, the one-shot call. |

The browser backend is swappable: anything with a `clear(url, *, proxy, timeout)`
returning a `BrowserResult` satisfies `ChallengeBrowser`, so an existing
Playwright or nodriver setup can be dropped in.

```python
from cfts_solver import DrissionBrowser, TurnstileSolver

# Headless is graded harder by Cloudflare; on a server, prefer xvfb.
solver = TurnstileSolver(browser=DrissionBrowser(headless=True))
```

## What it does not do

Interactive Turnstile widgets embedded in a site's own form -- a login page, a
signup form -- are not solved. This clears the interstitial Cloudflare puts in
front of a page, which is a different thing that happens to use the same widget.

A blocked IP is not a challenge and raises `BlockedError` rather than retrying:
no amount of waiting undoes a firewall rule. Route through a residential proxy
with `proxy=`, which is part of the cache key because a clearance is only good
from the IP that earned it.

-->

## License

[MIT License](
  <https://github.com/eggplants/cfts-solver/blob/master/LICENSE.txt>
)
