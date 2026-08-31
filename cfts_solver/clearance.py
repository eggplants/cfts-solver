"""The clearance a solved challenge yields, and where to keep it.

Cloudflare hands back a ``cf_clearance`` cookie, but the cookie on its own is
worthless: it is bound to the user agent that earned it, so the two have to
travel together or the next request is challenged again. :class:`Clearance`
keeps that pair intact, and :class:`ClearanceStore` keeps it on disk so a
second process does not have to launch a browser to learn the same thing.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .challenge import CLEARANCE_COOKIE

if TYPE_CHECKING:
    from collections.abc import Mapping

    from curl_cffi.requests import Session

#: How long a clearance is assumed good for. Cloudflare does not say, and the
#: bot-management cookie riding with it rolls over every 30 minutes, so expire
#: a shade earlier and re-solve rather than eat a surprise 403.
DEFAULT_TTL = timedelta(minutes=29)

#: Headers a real Chrome sends on a top-level navigation. Pairing them with
#: ``impersonate="chrome"`` keeps the replayed request consistent with the
#: browser that earned the clearance.
CHROME_HEADERS: Mapping[str, str] = {
    "accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8,"
        "application/signed-exchange;v=b3;q=0.7"
    ),
    "accept-language": "en-US,en;q=0.9",
    "upgrade-insecure-requests": "1",
}


@dataclass(frozen=True)
class Clearance:
    """A cleared Cloudflare challenge: cookies plus the user agent that won them.

    Attributes:
        domain (str): The host the cookies belong to.
        cookies (Mapping[str, str]): Every cookie the browser held when the
            challenge cleared, ``cf_clearance`` included.
        user_agent (str): The user agent the browser presented. Send anything
            else and Cloudflare rejects the cookie.
        issued_at (datetime): When the challenge was cleared.
        expires_at (datetime): When to stop trusting this clearance.
    """

    domain: str
    cookies: Mapping[str, str]
    user_agent: str
    issued_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime = field(
        default_factory=lambda: datetime.now(UTC) + DEFAULT_TTL,
    )

    @property
    def token(self) -> str:
        """The ``cf_clearance`` value.

        Returns:
            str: The clearance token, or an empty string if the site handed
                back none -- an unprotected page clears without one.
        """
        return self.cookies.get(CLEARANCE_COOKIE, "")

    @property
    def is_expired(self) -> bool:
        """Whether the clearance has outlived its assumed lifetime.

        Returns:
            bool: True once :attr:`expires_at` has passed.
        """
        return datetime.now(UTC) >= self.expires_at

    def as_headers(self) -> dict[str, str]:
        """Build the headers to send alongside the clearance.

        Returns:
            dict[str, str]: Chrome's navigation headers with the matching user
                agent and a ``cookie`` header.
        """
        headers = dict(CHROME_HEADERS)
        headers["user-agent"] = self.user_agent
        headers["cookie"] = "; ".join(f"{name}={value}" for name, value in self.cookies.items())
        return headers

    def apply(self, session: Session) -> None:
        """Load the clearance into a ``curl_cffi`` session.

        Sets every cookie on the session jar and pins the user agent, so the
        session keeps looking like the browser that cleared the challenge.

        Args:
            session (Session): The session to configure.
        """
        for name, value in self.cookies.items():
            session.cookies.set(name, value, domain=self.domain)
        session.headers.update({**CHROME_HEADERS, "user-agent": self.user_agent})

    def to_dict(self) -> dict[str, Any]:
        """Serialise the clearance.

        Returns:
            dict[str, Any]: A JSON-safe representation.
        """
        return {
            "domain": self.domain,
            "cookies": dict(self.cookies),
            "user_agent": self.user_agent,
            "issued_at": self.issued_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Clearance:
        """Reverse :meth:`to_dict`.

        Args:
            data (Mapping[str, Any]): A serialised clearance.

        Returns:
            Clearance: The restored clearance.
        """
        return cls(
            domain=str(data["domain"]),
            cookies=dict(data["cookies"]),
            user_agent=str(data["user_agent"]),
            issued_at=datetime.fromisoformat(str(data["issued_at"])),
            expires_at=datetime.fromisoformat(str(data["expires_at"])),
        )


def default_store_path() -> Path:
    """Where clearances live when the caller does not say.

    Returns:
        Path: A path under ``XDG_CACHE_HOME``, falling back to ``~/.cache``.
    """
    root = os.environ.get("XDG_CACHE_HOME")
    base = Path(root) if root else Path.home() / ".cache"
    return base / "cfts-solver" / "clearances.json"


def store_key(domain: str, proxy: str | None = None) -> str:
    """Build the key a clearance is filed under.

    A clearance is only good from the IP that earned it, so a proxy is part of
    the identity rather than an incidental detail.

    Args:
        domain (str): The host the clearance is for.
        proxy (str | None): The proxy it was earned through, if any.

    Returns:
        str: The store key.
    """
    return f"{domain}|{proxy or ''}"


class ClearanceStore:
    """A thread-safe, file-backed cache of clearances.

    Args:
        path (Path | str | None): Where to keep the JSON file. Defaults to
            :func:`default_store_path`.
        persist (bool): Set False to keep clearances in memory only, in which
            case ``path`` is ignored. :meth:`in_memory` says the same thing
            more legibly.
    """

    def __init__(self, path: Path | str | None = None, *, persist: bool = True) -> None:
        """Initialize the store and load whatever is already on disk."""
        self.path: Path | None = None
        if persist:
            self.path = Path(path) if path is not None else default_store_path()
        self._lock = threading.RLock()
        self._entries: dict[str, Clearance] = {}
        self._load()

    @classmethod
    def in_memory(cls) -> ClearanceStore:
        """Build a store that never touches the disk.

        Returns:
            ClearanceStore: A store scoped to this process.
        """
        return cls(persist=False)

    def _load(self) -> None:
        """Read the store file, ignoring anything unreadable."""
        if self.path is None:
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(raw, dict):
            return
        for key, entry in raw.items():
            try:
                self._entries[str(key)] = Clearance.from_dict(entry)
            except (KeyError, TypeError, ValueError):
                # One unreadable entry must not sink the rest of the file.
                continue

    def _save(self) -> None:
        """Write the store file atomically, so a crash cannot truncate it."""
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {key: entry.to_dict() for key, entry in self._entries.items()}
        handle, tmp_name = tempfile.mkstemp(
            dir=self.path.parent,
            prefix=".clearances.",
            suffix=".tmp",
        )
        tmp = Path(tmp_name)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as file:
                json.dump(data, file, indent=2)
                file.flush()
                os.fsync(file.fileno())
            tmp.replace(self.path)
        except OSError:
            tmp.unlink(missing_ok=True)
            raise

    def get(self, domain: str, proxy: str | None = None) -> Clearance | None:
        """Look up a clearance that is still good.

        Args:
            domain (str): The host the clearance is for.
            proxy (str | None): The proxy it was earned through, if any.

        Returns:
            Clearance | None: The clearance, or None if there is none or it
                has expired.
        """
        key = store_key(domain, proxy)
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if entry.is_expired:
                del self._entries[key]
                self._save()
                return None
            return entry

    def save(self, clearance: Clearance, proxy: str | None = None) -> None:
        """File a clearance.

        Args:
            clearance (Clearance): The clearance to keep.
            proxy (str | None): The proxy it was earned through, if any.
        """
        with self._lock:
            self._entries[store_key(clearance.domain, proxy)] = clearance
            self._save()

    def invalidate(self, domain: str, proxy: str | None = None) -> None:
        """Drop a clearance, for instance after it earned a fresh 403.

        Args:
            domain (str): The host the clearance is for.
            proxy (str | None): The proxy it was earned through, if any.
        """
        with self._lock:
            if self._entries.pop(store_key(domain, proxy), None) is not None:
                self._save()

    def purge_expired(self) -> int:
        """Forget every clearance that has expired.

        Returns:
            int: How many were dropped.
        """
        with self._lock:
            stale = [key for key, entry in self._entries.items() if entry.is_expired]
            for key in stale:
                del self._entries[key]
            if stale:
                self._save()
            return len(stale)

    def clear(self) -> None:
        """Forget every clearance."""
        with self._lock:
            self._entries.clear()
            self._save()


__all__ = (
    "CHROME_HEADERS",
    "DEFAULT_TTL",
    "Clearance",
    "ClearanceStore",
    "default_store_path",
    "store_key",
)
