# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Cloudflare Turnstile Solver

<!-- Replace this with what the project actually is: the problem it solves, the
     shape of its public surface, and the constraints worth knowing up front
     (required dependencies you deliberately do or do not have, and why). -->

`TODO.md` tracks the one-time repository setup that still has to be done by hand.

## Commands

Dependencies are managed with [uv](https://docs.astral.sh/uv/) and every task is
defined in `mise.toml`, which is the canonical list.

```bash
uv sync --all-groups                   # install runtime + dev + docs groups
mise run pytest                        # run the test suite
uv run pytest tests/test_turnstile_solver.py::test_version_is_available  # a single test
mise run ruff                          # format + autofix (uv format)
mise run ty                            # type check (uvx ty check)
mise run pymarkdown                    # markdown lint
mise run pyproject-fmt                 # normalize pyproject.toml
mise run pre-commit                    # ruff + ty + pymarkdown + pyproject-fmt
mise run ci                            # pre-commit + pytest-cov -- what CI runs
mise run build                         # build sdist + wheel
mise run docs                          # pdoc API docs into ./docs
mise run pinup                         # update the pinned action/image digests
```

The venv is tied to the absolute repo path (`uv sync` bakes it into script shebangs). If the
repo directory gets renamed or moved, delete `.venv/` and `uv sync` again rather than debugging
"No such file or directory" / `ModuleNotFoundError` -- it is a stale interpreter path, not a
code bug.

Lint config lives in `pyproject.toml`: Ruff with `lint.select = ["ALL"]` and `line-length = 120`.
Prefer a targeted `lint.per-file-ignores` entry with a comment over a scattered `# noqa`.

## Architecture

<!-- Describe the modules and how they are layered, in dependency order, and say
     what each one is responsible for. Name the invariants that are easy to break
     and the reason they exist -- that is the part that is not in the code. -->

- **`turnstile_solver/__init__.py`** -- package version, read from the installed
  distribution metadata (`0.0.0` when running from a source tree with no tags).

## Versioning and releases

Versions come from git tags via `uv-dynamic-versioning`; nothing in the repo hard-codes one.
Pushing a `v*.*.*` tag runs `release.yml`, which creates the GitHub release and then publishes to
PyPI.

## Testing conventions

Tests live in `tests/` and mirror the module split 1:1. `tests/**` has its own
`lint.per-file-ignores` block, so assertions and missing annotations are fine there.
