"""Small, careful HTTP client for DayOS's optional online features.

* Only http(s) URLs; a timeout on every request; responses are size-capped.
* No automatic retries and no background polling: callers fetch on a schedule or
  when the user presses Refresh, and use :class:`HttpCache` in between.
* HTTP 429 / 503 with ``Retry-After`` makes that host wait before it is asked again.
* Nothing about requests is logged except host and status (never query strings,
  headers or bodies, which may hold tokens or personal data).

Requests run on worker threads; the cache is used from the UI thread.
"""

from __future__ import annotations

import json
import logging
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from src.version import APP_VERSION

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 20.0
MAX_BYTES = 3 * 1024 * 1024
USER_AGENT = f"DayOS/{APP_VERSION} (personal desktop app; +https://github.com/etcofficials/DayOS)"

_blocked_until: dict[str, float] = {}
_lock = threading.Lock()


class HttpError(Exception):
    """kind: offline, timeout, rate_limited, http, too_large, bad_url, auth."""

    def __init__(self, kind: str, message: str, status: int | None = None, retry_after: float | None = None):
        super().__init__(message)
        self.kind = kind
        self.status = status
        self.retry_after = retry_after


@dataclass
class Response:
    status: int
    body: bytes
    headers: dict[str, str] = field(default_factory=dict)

    def json(self):
        return json.loads(self.body.decode("utf-8"))


def _host(url: str) -> str:
    return urllib.parse.urlsplit(url).hostname or ""


def _retry_after(value: str | None) -> float:
    if not value:
        return 300.0
    try:
        return max(30.0, min(float(value), 6 * 3600))
    except ValueError:
        return 300.0


def request(url: str, *, method: str = "GET", headers: dict | None = None, data: bytes | None = None,
            timeout: float = DEFAULT_TIMEOUT, max_bytes: int = MAX_BYTES) -> Response:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("https", "http") or not parts.hostname:
        raise HttpError("bad_url", "Only web (http/https) addresses can be used.")
    host = parts.hostname
    with _lock:
        until = _blocked_until.get(host, 0.0)
    if until > time.time():
        wait = int(until - time.time())
        raise HttpError("rate_limited", f"{host} asked DayOS to wait; try again in about {max(1, wait // 60)} min.",
                        retry_after=wait)
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as resp:
            body = resp.read(max_bytes + 1)
            status = resp.status
            hdrs = {k.lower(): v for k, v in resp.headers.items()}
    except urllib.error.HTTPError as exc:
        status = exc.code
        log.info("HTTP %s from %s", status, host)
        if status in (429, 503):
            delay = _retry_after(exc.headers.get("Retry-After") if exc.headers else None)
            with _lock:
                _blocked_until[host] = time.time() + delay
            raise HttpError("rate_limited", f"{host} is busy or limiting requests. DayOS will wait before asking "
                                            "again.", status, delay) from None
        if status in (401, 403):
            raise HttpError("auth", f"{host} refused the request ({status}). Check the credentials or access.",
                            status) from None
        raise HttpError("http", f"{host} answered with an error ({status}).", status) from None
    except (socket.timeout, TimeoutError):
        raise HttpError("timeout", f"{host} didn't answer in time.") from None
    except (urllib.error.URLError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, (socket.timeout, TimeoutError)):
            raise HttpError("timeout", f"{host} didn't answer in time.") from None
        raise HttpError("offline", "No internet connection (or the service can't be reached).") from None
    if len(body) > max_bytes:
        raise HttpError("too_large", f"The response from {host} was larger than expected.")
    return Response(status, body, hdrs)


def get_json(url: str, **kw):
    try:
        return request(url, headers={"Accept": "application/json", **kw.pop("headers", {})}, **kw).json()
    except (ValueError, UnicodeDecodeError):
        raise HttpError("http", "The service sent data DayOS couldn't read.") from None


class HttpCache:
    """Cached responses in the ``http_cache`` table (rebuildable; never exported)."""

    def __init__(self, db) -> None:
        self.db = db

    def get(self, key: str, max_age: timedelta | None = None) -> tuple[object, datetime] | None:
        row = self.db.query_one("SELECT value, fetched_at FROM http_cache WHERE key = ?", (key,))
        if row is None:
            return None
        try:
            fetched = datetime.fromisoformat(row["fetched_at"])
            value = json.loads(row["value"])
        except (ValueError, TypeError):
            return None
        if max_age is not None and datetime.now() - fetched > max_age:
            return None
        return value, fetched

    def put(self, key: str, value: object) -> datetime:
        stamp = datetime.now().replace(microsecond=0)
        with self.db.transaction():
            self.db.execute("INSERT INTO http_cache (key, value, fetched_at) VALUES (?, ?, ?) ON CONFLICT(key) DO "
                            "UPDATE SET value = excluded.value, fetched_at = excluded.fetched_at",
                            (key, json.dumps(value, ensure_ascii=False), stamp.isoformat(sep=" ")))
        return stamp

    def delete_prefix(self, prefix: str) -> None:
        with self.db.transaction():
            self.db.execute("DELETE FROM http_cache WHERE key LIKE ?", (prefix.replace("%", "") + "%",))


def describe_age(when: datetime, now: datetime | None = None) -> str:
    now = now or datetime.now()
    minutes = int((now - when).total_seconds() // 60)
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes} min ago"
    if minutes < 48 * 60:
        return f"{minutes // 60} h ago"
    return when.strftime("%d %b %Y")
