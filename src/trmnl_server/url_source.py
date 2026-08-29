"""Non-Home-Assistant data sources for trmnl-server.

Fetches text from an arbitrary HTTP(S) URL and extracts a value from it,
either with a jq-style JSON path or a regex. Fetches happen on a background
thread pool and are cached, so the render path never waits on the network.
"""

import json
import re
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, wait
from typing import TYPE_CHECKING
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import urlopen

if TYPE_CHECKING:
    from logging import Logger
    from .models import ComponentConfig, Config

_INDEX_RE = re.compile(r"^\[(-?\d+)\]$")

DEFAULT_CACHE_TTL: int = 300
DEFAULT_TIMEOUT: int = 10
MAX_TIMEOUT: int = 60
MAX_BYTES: int = 1_048_576
ALLOWED_SCHEMES: frozenset[str] = frozenset({"http", "https"})

# url -> (attempted_at, body or None). Written on every attempt so a dead URL
# backs off to one try per cache_ttl; the body survives a failed refresh.
_cache: dict[str, tuple[float, str | None]] = {}
_inflight: dict[str, Future] = {}
_lock = threading.Lock()
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="url-source")


def _json_path(obj: object, path: str) -> object | None:
    """Resolve a basic jq-style path against a decoded JSON object.

    Supports dot-separated keys and bracketed integer indices, e.g.
    ``.data.items[0].name``. The leading dot is optional.

    Args:
        obj: Decoded JSON value to traverse.
        path: The path expression.

    Returns:
        The value at the path, or None if any step is missing, out of range,
        traverses into a non-container, or is malformed.
    """
    current: object = obj
    for token in _tokenise_path(path):
        match = _INDEX_RE.match(token)
        if match is not None:
            if not isinstance(current, list):
                return None
            index = int(match.group(1))
            if not -len(current) <= index < len(current):
                return None
            current = current[index]
        elif token.startswith("["):
            return None  # malformed index, e.g. [x]
        else:
            if not isinstance(current, dict) or token not in current:
                return None
            current = current[token]
    return current


def _tokenise_path(path: str) -> list[str]:
    """Split a path into key and ``[index]`` tokens.

    Args:
        path: The path expression, with or without a leading dot.

    Returns:
        Token list; empty for an empty path (the identity path).
    """
    tokens: list[str] = []
    for part in path.lstrip(".").split("."):
        if not part:
            continue
        head, _, rest = part.partition("[")
        if head:
            tokens.append(head)
        if rest:
            tokens.extend(f"[{chunk}" for chunk in rest.split("["))
        elif "[" in part:
            # Dangling bracket with nothing after it is malformed
            tokens.append("[")
    return tokens


def _stringify(value: object) -> str | None:
    """Render an extracted JSON value as display text.

    Strings pass through unquoted; everything else is JSON-encoded, so
    containers become JSON text rather than a Python repr and booleans render
    as ``true``/``false``.

    Args:
        value: The extracted value.

    Returns:
        The text, or None for JSON null.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value)


def extract_value(
    body: str,
    *,
    json_path: str | None,
    regex: str | None,
    logger: "Logger",
) -> str | None:
    """Extract display text from a response body.

    Applies ``json_path`` first (if set), then ``regex`` (if set) to the
    result. With neither set the stripped body is returned.

    Args:
        body: The raw response body.
        json_path: Optional jq-style path.
        regex: Optional pattern; group 1 if the pattern has groups, else group 0.
        logger: Logger for extraction warnings.

    Returns:
        The extracted text, or None if any step fails to produce a value.
    """
    if not body:
        return None

    value: object = body
    if json_path:
        try:
            decoded = json.loads(body)
        except ValueError:
            logger.warning("Response is not valid JSON; cannot apply json_path %r.", json_path)
            return None
        value = _json_path(decoded, json_path)
        if value is None:
            logger.warning("json_path %r matched nothing in the response.", json_path)
            return None

    text: str | None = _stringify(value)
    if text is None:
        return None

    if regex:
        try:
            match = re.search(regex, text)
        except re.error as e:
            logger.warning("Invalid regex %r: %s", regex, e)
            return None
        if match is None:
            logger.warning("regex %r matched nothing in the response.", regex)
            return None
        text = match.group(1) if match.re.groups else match.group(0)

    text = text.strip()
    return text or None


def _redact(url: str) -> str:
    """Strip the query string and fragment from a URL for logging.

    API keys are documented to live in the query string and logs are persisted
    to disk, so no log line may carry a URL verbatim.

    Args:
        url: The URL to redact.

    Returns:
        Scheme, netloc and path only.
    """
    try:
        parts = urlsplit(url)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    except ValueError:
        return "<unparseable url>"


def _coerce_int(
    value: object,
    default: int,
    *,
    name: str,
    logger: "Logger",
    maximum: int | None = None,
) -> int:
    """Coerce a component config value to a positive int.

    Rejects bool (a bool is an int in Python but never a valid duration),
    non-int, and non-positive values, warning and falling back to default.
    Mirrors how `components.py` validates `hours` and `columns`.

    Args:
        value: The raw config value.
        default: Value used when value is missing or invalid.
        name: Field name, for the warning message.
        logger: Logger for the warning.
        maximum: Optional ceiling that a valid value is clamped to.

    Returns:
        A positive int, at most maximum if given.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        logger.warning("Invalid %s (%r); defaulting to %d.", name, value, default)
        value = default
    if maximum is not None and value > maximum:
        return maximum
    return value


def _fetch(url: str, timeout: int, logger: "Logger") -> None:
    """Fetch a URL on a background thread and update the cache.

    Runs entirely off the caller's thread (submitted to the module's
    executor). Records `attempted_at` in a `finally` block so a failed
    fetch also backs off for a full `cache_ttl` instead of being retried on
    every render, and a failure never blanks an already-cached body. Clears
    its own in-flight entry when done.

    Args:
        url: The URL to fetch.
        timeout: Socket timeout in seconds for this call only; never bounds
            the caller of `get_url_text`.
        logger: Logger for fetch errors and size-cap warnings.
    """
    body: str | None = None
    try:
        with urlopen(url, timeout=timeout) as response:
            data = response.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            logger.warning(
                "Response from %s exceeds %d bytes; truncating.", _redact(url), MAX_BYTES
            )
            data = data[:MAX_BYTES]
        body = data.decode("utf-8", errors="replace")
    except HTTPError as e:
        logger.error("HTTP error fetching %s: %d %s", _redact(url), e.code, e.reason)
    except URLError as e:
        logger.error("URL error fetching %s: %s", _redact(url), e.reason)
    except Exception as e:  # noqa: BLE001 - never raise from library code
        logger.error("Unexpected error fetching %s: %s", _redact(url), e)
    finally:
        with _lock:
            if body is None:
                previous = _cache.get(url)
                body = previous[1] if previous is not None else None
            _cache[url] = (time.time(), body)
            _inflight.pop(url, None)


def get_url_text(
    url: str,
    *,
    cache_ttl: int,
    timeout: int,
    logger: "Logger",
    now: float | None = None,
) -> str | None:
    """Read the cached text for a URL without ever blocking on the network.

    Reads the cache, decides whether a background fetch should be submitted
    (cold cache, or an entry older than `cache_ttl`), and returns
    immediately. Never calls `Future.result()`, never sleeps, and never
    holds the module lock across the HTTP call - a stalled or dead URL must
    never delay a render.

    Args:
        url: The URL to read.
        cache_ttl: Max age in seconds before a cached body is stale enough
            to trigger a background refresh.
        timeout: Socket timeout in seconds, passed through to the
            background fetch only.
        logger: Logger for fetch errors and scheme rejection.
        now: Override for the current time (for tests); defaults to
            `time.time()`.

    Returns:
        The cached body text, or None if nothing has been fetched
        successfully yet.
    """
    current_time = now if now is not None else time.time()

    if not isinstance(url, str):
        logger.warning("Refusing to fetch: url is not a string.")
        return None
    try:
        scheme = urlsplit(url).scheme
    except ValueError:
        logger.warning("Refusing to fetch %s: unparseable URL.", _redact(url))
        return None
    if scheme not in ALLOWED_SCHEMES:
        logger.warning("Refusing to fetch %s: unsupported scheme.", _redact(url))
        return None

    with _lock:
        cached = _cache.get(url)
        needs_fetch = cached is None or (current_time - cached[0] >= cache_ttl)
        if needs_fetch and url not in _inflight:
            _inflight[url] = _executor.submit(_fetch, url, timeout, logger)

    return cached[1] if cached is not None else None


def fetch_url_value(component: "ComponentConfig", logger: "Logger") -> str | None:
    """Fetch and extract the display value for a url-type component.

    Reads `url`, `json_path`, `regex`, `cache_ttl` and `timeout` from the
    component config and applies `extract_value` to whatever text is
    currently cached for the url. Never blocks on the network - see
    `get_url_text`.

    Args:
        component: The dashboard component config.
        logger: Logger for fetch and extraction errors.

    Returns:
        Extracted display text, or None if there's no url configured,
        nothing is cached yet, or extraction fails.
    """
    url = component.get("url")
    if not url:
        return None

    cache_ttl = _coerce_int(
        component.get("cache_ttl", DEFAULT_CACHE_TTL),
        DEFAULT_CACHE_TTL,
        name="cache_ttl",
        logger=logger,
    )
    timeout = _coerce_int(
        component.get("timeout", DEFAULT_TIMEOUT),
        DEFAULT_TIMEOUT,
        name="timeout",
        logger=logger,
        maximum=MAX_TIMEOUT,
    )

    body = get_url_text(url, cache_ttl=cache_ttl, timeout=timeout, logger=logger)
    if body is None:
        return None
    return extract_value(
        body,
        json_path=component.get("json_path"),
        regex=component.get("regex"),
        logger=logger,
    )


def prefetch(config: "Config", logger: "Logger") -> None:
    """Submit a background fetch for every distinct url-type component url.

    Called once at startup so the first render of each dashboard is not the
    first fetch. Deduplicates by url so a url shared across components or
    dashboards is only fetched once. Never blocks.

    Args:
        config: The full server config.
        logger: Logger for fetch errors.
    """
    seen: set[str] = set()
    for dashboard in config.get("dashboards", []):
        for component in dashboard.get("components", []):
            if component.get("type") != "url":
                continue
            url = component.get("url")
            if not url or url in seen:
                continue
            seen.add(url)
            cache_ttl = _coerce_int(
                component.get("cache_ttl", DEFAULT_CACHE_TTL),
                DEFAULT_CACHE_TTL,
                name="cache_ttl",
                logger=logger,
            )
            timeout = _coerce_int(
                component.get("timeout", DEFAULT_TIMEOUT),
                DEFAULT_TIMEOUT,
                name="timeout",
                logger=logger,
                maximum=MAX_TIMEOUT,
            )
            get_url_text(url, cache_ttl=cache_ttl, timeout=timeout, logger=logger)


def reset_cache() -> None:
    """Clear all cached bodies and in-flight fetch state.

    Test-only helper; production code never needs to clear the cache.
    """
    with _lock:
        _cache.clear()
        _inflight.clear()


def _wait_for_pending(timeout: float = 10.0) -> bool:
    """Block until currently in-flight fetches complete.

    Test-only synchronization helper. Takes a snapshot of the in-flight
    futures under the lock, then waits on that snapshot outside the lock so
    the wait never holds the lock across the HTTP call and fetches
    submitted after the snapshot don't extend this wait.

    Args:
        timeout: Max seconds to wait for the snapshot to complete.

    Returns:
        True if every snapshotted future completed; False if the timeout
        elapsed with some still running.
    """
    with _lock:
        futures = list(_inflight.values())
    if not futures:
        return True
    _done, not_done = wait(futures, timeout=timeout)
    return not not_done
