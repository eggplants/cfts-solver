""".. include:: ../README.md"""  # noqa: D415

from __future__ import annotations

import importlib.metadata

try:
    __version__ = importlib.metadata.version(__name__)
except importlib.metadata.PackageNotFoundError:  # pragma: no cover
    __version__ = "0.0.0"
