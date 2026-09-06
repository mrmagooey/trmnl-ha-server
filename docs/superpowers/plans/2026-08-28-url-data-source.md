# URL Data Source Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `type: url` dashboard component that renders text fetched from an arbitrary HTTP(S) URL, with jq-style JSON path extraction, regex extraction, TTL caching, and a render path that never blocks.

**Architecture:** One new module `src/trmnl_server/url_source.py` owns fetching, caching and extraction. Fetches run on a background `ThreadPoolExecutor`; the render thread only ever reads the cache and returns immediately. `render_dashboard_image` gains one branch, and the existing entity renderer draws the result.

**Tech Stack:** Python 3.12 stdlib only (`urllib.request`, `json`, `re`, `threading`, `concurrent.futures`). Pillow and PyYAML are the only runtime dependencies and **no new dependency may be added**.

**Spec:** `docs/superpowers/specs/2026-08-28-url-data-source-design.md`

## Global Constraints

- **No new runtime dependencies.** stdlib only. Adding `jq`, `jsonpath`, `requests` or `httpx` fails the task.
- **Never raise from library code.** Log the error and return `None` / empty, matching `hass_client.py` and `config.py`.
- **`_validate_config` warns, never raises.**
- **URLs must be redacted in every log message**, in `url_source.py` and `config.py` alike. Log scheme + netloc + path only. Never log a URL with `%r` or `%s` unredacted — logs are persisted to `/logs` via `RotatingFileHandler` and API keys live in the query string.
- **The render thread must never wait on a fetch.** No `future.result()`, no `sleep`, no lock held across I/O on the render path.
- Type hints on every parameter and return (modern `X | None` syntax). Google-style docstrings on public functions.
- Tests use `unittest.TestCase` with `mock.patch`, file `tests/test_<module>.py`, class `Test<Thing>`.
- Run the full suite (`uv run pytest tests/ -v`) before every commit.
- All work happens in the worktree `/home/dev/projects/trmnl-url-source` on branch `feat/url-data-source`. Never commit to `main`.

---

## File Structure

- **Create** `src/trmnl_server/url_source.py` — fetch, cache, extraction. The whole feature's logic.
- **Create** `tests/test_url_source.py` — unit tests for the above.
- **Create** `tests/test_url_source_e2e.py` — real-HTTP end-to-end test.
- **Modify** `src/trmnl_server/models.py` — `ComponentConfig` fields.
- **Modify** `src/trmnl_server/config.py` — validation.
- **Modify** `src/trmnl_server/components.py` — render branch + dispatch.
- **Modify** `src/trmnl_server/server.py` — startup prefetch.
- **Modify** `tests/test_components.py`, `tests/test_config.py`, `tests/test_golden.py` — integration coverage.
- **Modify** `README.md`, `examples/config.yaml`, `CHANGELOG.md` — docs.

---

### Task 1: Extraction — `_json_path`, `_stringify`, `extract_value`

Pure functions, no I/O. Build these first so later tasks have a working extractor.

**Files:**
- Create: `src/trmnl_server/url_source.py`
- Test: `tests/test_url_source.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `_json_path(obj: object, path: str) -> object | None`
  - `_stringify(value: object) -> str | None`
  - `extract_value(body: str, *, json_path: str | None, regex: str | None, logger: "Logger") -> str | None`

- [ ] **Step 1: Write the failing tests**

```python
"""Unit tests for the URL data source module."""

import logging
import unittest
from unittest import mock

from trmnl_server.url_source import _json_path, _stringify, extract_value

mock_logger = mock.Mock(spec=logging.Logger)


class TestJsonPath(unittest.TestCase):
    """Tests for the mini jq-style path parser."""

    def test_top_level_key(self):
        """A single dotted key reads a top-level field."""
        self.assertEqual(_json_path({"a": 1}, ".a"), 1)

    def test_leading_dot_optional(self):
        """A path without the leading dot behaves identically."""
        self.assertEqual(_json_path({"a": 1}, "a"), 1)

    def test_nested_keys(self):
        """Dots traverse nested objects."""
        self.assertEqual(_json_path({"a": {"b": {"c": "x"}}}, ".a.b.c"), "x")

    def test_array_index(self):
        """Bracketed integers index into lists."""
        self.assertEqual(_json_path({"a": [10, 20, 30]}, ".a[1]"), 20)

    def test_nested_index_then_key(self):
        """Indices and keys can be chained."""
        self.assertEqual(_json_path({"a": [{"b": 7}]}, ".a[0].b"), 7)

    def test_root_index(self):
        """A path may index a top-level array."""
        self.assertEqual(_json_path([{"b": 7}], "[0].b"), 7)

    def test_missing_key_returns_none(self):
        """An absent key yields None rather than raising."""
        self.assertIsNone(_json_path({"a": 1}, ".b"))

    def test_index_out_of_range_returns_none(self):
        """An out-of-range index yields None rather than raising."""
        self.assertIsNone(_json_path({"a": [1]}, ".a[5]"))

    def test_index_into_non_list_returns_none(self):
        """Indexing a dict yields None."""
        self.assertIsNone(_json_path({"a": {"b": 1}}, ".a[0]"))

    def test_key_into_non_dict_returns_none(self):
        """Traversing into a scalar yields None."""
        self.assertIsNone(_json_path({"a": 5}, ".a.b"))

    def test_empty_path_returns_whole_object(self):
        """An empty path is the identity."""
        self.assertEqual(_json_path({"a": 1}, ""), {"a": 1})

    def test_malformed_path_returns_none(self):
        """An unparseable index yields None rather than raising."""
        self.assertIsNone(_json_path({"a": [1]}, ".a[x]"))


class TestStringify(unittest.TestCase):
    """Tests for value stringification."""

    def test_string_passes_through(self):
        """A string is returned unchanged, not JSON-quoted."""
        self.assertEqual(_stringify("hi"), "hi")

    def test_int(self):
        """Integers render without a decimal point."""
        self.assertEqual(_stringify(42), "42")

    def test_float(self):
        """Floats keep their fractional part."""
        self.assertEqual(_stringify(42.5), "42.5")

    def test_bool_is_json_lowercase(self):
        """Booleans render as JSON true/false, not Python True/False."""
        self.assertEqual(_stringify(True), "true")

    def test_none_returns_none(self):
        """JSON null yields None so the panel shows 'No data'."""
        self.assertIsNone(_stringify(None))

    def test_container_is_json_text(self):
        """Lists and dicts render as JSON text, not a Python repr."""
        self.assertEqual(_stringify({"a": 1}), '{"a": 1}')
        self.assertEqual(_stringify([1, 2]), "[1, 2]")


class TestExtractValue(unittest.TestCase):
    """Tests for the extraction pipeline."""

    def test_raw_body_when_no_extractors(self):
        """With neither extractor set the stripped body is returned."""
        self.assertEqual(
            extract_value("  hello  ", json_path=None, regex=None, logger=mock_logger),
            "hello",
        )

    def test_json_path_only(self):
        """json_path pulls a field out of a JSON body."""
        self.assertEqual(
            extract_value('{"a": {"b": "x"}}', json_path=".a.b", regex=None, logger=mock_logger),
            "x",
        )

    def test_regex_only(self):
        """regex scrapes an unstructured body."""
        self.assertEqual(
            extract_value("temp is 21.5C", json_path=None, regex=r"([0-9.]+)C", logger=mock_logger),
            "21.5",
        )

    def test_regex_without_groups_returns_whole_match(self):
        """A group-less pattern returns the entire match."""
        self.assertEqual(
            extract_value("temp is 21.5C", json_path=None, regex=r"[0-9.]+", logger=mock_logger),
            "21.5",
        )

    def test_json_path_then_regex(self):
        """Both extractors apply in order: path first, then regex."""
        self.assertEqual(
            extract_value(
                '{"a": "temp 21.5C"}', json_path=".a", regex=r"([0-9.]+)", logger=mock_logger
            ),
            "21.5",
        )

    def test_regex_sees_json_text_for_containers(self):
        """A path landing on a container feeds regex JSON text, not a Python repr."""
        self.assertEqual(
            extract_value(
                '{"a": {"b": 1}}', json_path=".a", regex=r'"b": (\d+)', logger=mock_logger
            ),
            "1",
        )

    def test_no_regex_match_returns_none(self):
        """A non-matching pattern yields None."""
        self.assertIsNone(
            extract_value("abc", json_path=None, regex=r"\d+", logger=mock_logger)
        )

    def test_invalid_json_returns_none(self):
        """A json_path against a non-JSON body yields None and warns."""
        self.assertIsNone(
            extract_value("not json", json_path=".a", regex=None, logger=mock_logger)
        )

    def test_json_null_returns_none(self):
        """A path resolving to JSON null yields None, not the text 'null'."""
        self.assertIsNone(
            extract_value('{"a": null}', json_path=".a", regex=None, logger=mock_logger)
        )

    def test_invalid_regex_returns_none(self):
        """An uncompilable pattern yields None and warns rather than raising."""
        self.assertIsNone(
            extract_value("abc", json_path=None, regex=r"([", logger=mock_logger)
        )

    def test_empty_body_returns_none(self):
        """An empty body yields None."""
        self.assertIsNone(
            extract_value("", json_path=None, regex=None, logger=mock_logger)
        )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/dev/projects/trmnl-url-source && uv run pytest tests/test_url_source.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'trmnl_server.url_source'`

- [ ] **Step 3: Write the implementation**

Create `src/trmnl_server/url_source.py` with the module docstring, imports, and these functions. `_json_path` walks a token list; `extract_value` chains path → regex.

```python
"""Non-Home-Assistant data sources for trmnl-server.

Fetches text from an arbitrary HTTP(S) URL and extracts a value from it,
either with a jq-style JSON path or a regex. Fetches happen on a background
thread pool and are cached, so the render path never waits on the network.
"""

import json
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from logging import Logger

_INDEX_RE = re.compile(r"^\[(-?\d+)\]$")


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
            tokens.extend(f"[{chunk}" for chunk in rest.split("[") if chunk)
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /home/dev/projects/trmnl-url-source && uv run pytest tests/test_url_source.py -v`
Expected: PASS, all tests in `TestJsonPath`, `TestStringify`, `TestExtractValue`.

- [ ] **Step 5: Commit**

```bash
cd /home/dev/projects/trmnl-url-source
git add src/trmnl_server/url_source.py tests/test_url_source.py
git commit -m "feat: jq-style path and regex extraction for URL sources"
```

---

### Task 2: Fetch, cache and the non-blocking read path

**Files:**
- Modify: `src/trmnl_server/url_source.py`
- Test: `tests/test_url_source.py`

**Interfaces:**
- Consumes: `extract_value` from Task 1.
- Produces:
  - `DEFAULT_CACHE_TTL = 300`, `DEFAULT_TIMEOUT = 10`, `MAX_TIMEOUT = 60`, `MAX_BYTES = 1_048_576`
  - `_redact(url: str) -> str`
  - `_fetch(url: str, timeout: int, logger: "Logger") -> None`
  - `get_url_text(url: str, *, cache_ttl: int, timeout: int, logger: "Logger", now: float | None = None) -> str | None`
  - `fetch_url_value(component: "ComponentConfig", logger: "Logger") -> str | None`
  - `prefetch(config: "Config", logger: "Logger") -> None`
  - `reset_cache() -> None`
  - `_wait_for_pending(timeout: float = 10.0) -> bool`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_url_source.py`:

```python
import time
from trmnl_server import url_source
from trmnl_server.url_source import (
    MAX_BYTES,
    MAX_TIMEOUT,
    _redact,
    fetch_url_value,
    get_url_text,
    prefetch,
    reset_cache,
)


class _FakeResponse:
    """Minimal stand-in for the object urlopen returns as a context manager."""

    def __init__(self, body: bytes, delay: float = 0.0):
        self._body = body
        self._delay = delay

    def __enter__(self):
        if self._delay:
            time.sleep(self._delay)
        return self

    def __exit__(self, *exc):
        return False

    def read(self, n: int = -1) -> bytes:
        return self._body[:n] if n and n > 0 else self._body


class TestRedact(unittest.TestCase):
    """Tests that URLs never reach the logs with their query string."""

    def test_strips_query_string(self):
        """The query string, where API keys live, is removed."""
        self.assertEqual(
            _redact("https://api.example.com/v1/price?apikey=SECRET&x=1"),
            "https://api.example.com/v1/price",
        )

    def test_strips_fragment(self):
        """The fragment is removed too."""
        self.assertEqual(_redact("https://e.com/p#frag"), "https://e.com/p")

    def test_keeps_scheme_host_path(self):
        """Enough of the URL survives to identify the source in a log."""
        self.assertEqual(_redact("http://e.com/a/b"), "http://e.com/a/b")

    def test_unparseable_url_does_not_raise(self):
        """A garbage value is still redacted to something safe."""
        self.assertNotIn("SECRET", _redact("::::?k=SECRET"))


class TestGetUrlText(unittest.TestCase):
    """Tests for the caching, non-blocking read path."""

    def setUp(self):
        reset_cache()

    def test_cold_cache_returns_none_immediately(self):
        """A cold read returns None at once and does not wait for the fetch."""
        with mock.patch.object(
            url_source, "urlopen", return_value=_FakeResponse(b"hi", delay=2.0)
        ):
            t0 = time.perf_counter()
            result = get_url_text(
                "http://e.com/a", cache_ttl=300, timeout=10, logger=mock_logger
            )
            elapsed = time.perf_counter() - t0
            self.assertIsNone(result)
            self.assertLess(elapsed, 0.5, "render path must not wait on the fetch")
            url_source._wait_for_pending()

    def test_value_available_after_fetch_completes(self):
        """Once the background fetch lands, the next read returns the body."""
        with mock.patch.object(url_source, "urlopen", return_value=_FakeResponse(b"hi")):
            get_url_text("http://e.com/a", cache_ttl=300, timeout=10, logger=mock_logger)
            url_source._wait_for_pending()
            self.assertEqual(
                get_url_text("http://e.com/a", cache_ttl=300, timeout=10, logger=mock_logger),
                "hi",
            )

    def test_fresh_cache_does_not_refetch(self):
        """Inside the TTL no second request is made."""
        with mock.patch.object(
            url_source, "urlopen", return_value=_FakeResponse(b"hi")
        ) as m:
            get_url_text("http://e.com/a", cache_ttl=300, timeout=10, logger=mock_logger)
            url_source._wait_for_pending()
            get_url_text("http://e.com/a", cache_ttl=300, timeout=10, logger=mock_logger)
            url_source._wait_for_pending()
            self.assertEqual(m.call_count, 1)

    def test_stale_cache_serves_stale_value_and_refreshes(self):
        """Past the TTL the stale value is returned and a refresh is scheduled."""
        with mock.patch.object(url_source, "urlopen", return_value=_FakeResponse(b"old")):
            get_url_text("http://e.com/a", cache_ttl=300, timeout=10, logger=mock_logger)
            url_source._wait_for_pending()
        with mock.patch.object(
            url_source, "urlopen", return_value=_FakeResponse(b"new")
        ) as m:
            later = time.time() + 301
            self.assertEqual(
                get_url_text(
                    "http://e.com/a", cache_ttl=300, timeout=10, logger=mock_logger, now=later
                ),
                "old",
            )
            url_source._wait_for_pending()
            self.assertEqual(m.call_count, 1)

    def test_per_caller_ttl_on_a_shared_url(self):
        """Two components on one URL each judge freshness by their own TTL."""
        with mock.patch.object(url_source, "urlopen", return_value=_FakeResponse(b"v")):
            get_url_text("http://e.com/a", cache_ttl=60, timeout=10, logger=mock_logger)
            url_source._wait_for_pending()
        with mock.patch.object(
            url_source, "urlopen", return_value=_FakeResponse(b"v")
        ) as m:
            later = time.time() + 120
            get_url_text(
                "http://e.com/a", cache_ttl=600, timeout=10, logger=mock_logger, now=later
            )
            url_source._wait_for_pending()
            self.assertEqual(m.call_count, 0, "lax TTL should ride along on the cached body")
            get_url_text(
                "http://e.com/a", cache_ttl=60, timeout=10, logger=mock_logger, now=later
            )
            url_source._wait_for_pending()
            self.assertEqual(m.call_count, 1, "strict TTL should trigger the refresh")

    def test_failed_fetch_is_not_retried_within_ttl(self):
        """attempted_at is recorded on failure, so a dead URL backs off."""
        with mock.patch.object(
            url_source, "urlopen", side_effect=URLError("boom")
        ) as m:
            get_url_text("http://e.com/a", cache_ttl=300, timeout=10, logger=mock_logger)
            url_source._wait_for_pending()
            get_url_text("http://e.com/a", cache_ttl=300, timeout=10, logger=mock_logger)
            url_source._wait_for_pending()
            self.assertEqual(m.call_count, 1)

    def test_failed_refresh_keeps_serving_stale_body(self):
        """A refresh failure does not blank an already-cached value."""
        with mock.patch.object(url_source, "urlopen", return_value=_FakeResponse(b"good")):
            get_url_text("http://e.com/a", cache_ttl=300, timeout=10, logger=mock_logger)
            url_source._wait_for_pending()
        with mock.patch.object(url_source, "urlopen", side_effect=URLError("boom")):
            later = time.time() + 301
            get_url_text(
                "http://e.com/a", cache_ttl=300, timeout=10, logger=mock_logger, now=later
            )
            url_source._wait_for_pending()
            self.assertEqual(
                get_url_text(
                    "http://e.com/a", cache_ttl=300, timeout=10, logger=mock_logger, now=later
                ),
                "good",
            )

    def test_non_http_scheme_is_refused(self):
        """file:// and friends are never fetched."""
        with mock.patch.object(url_source, "urlopen") as m:
            self.assertIsNone(
                get_url_text("file:///etc/passwd", cache_ttl=300, timeout=10, logger=mock_logger)
            )
            url_source._wait_for_pending()
            m.assert_not_called()

    def test_response_is_capped(self):
        """At most MAX_BYTES is read from a response."""
        with mock.patch.object(
            url_source, "urlopen", return_value=_FakeResponse(b"x" * (MAX_BYTES + 5000))
        ):
            get_url_text("http://e.com/a", cache_ttl=300, timeout=10, logger=mock_logger)
            url_source._wait_for_pending()
            body = get_url_text(
                "http://e.com/a", cache_ttl=300, timeout=10, logger=mock_logger
            )
            self.assertEqual(len(body), MAX_BYTES)

    def test_logs_never_contain_the_query_string(self):
        """A failing fetch logs a redacted URL."""
        logger = mock.Mock(spec=logging.Logger)
        with mock.patch.object(url_source, "urlopen", side_effect=URLError("boom")):
            get_url_text(
                "http://e.com/a?apikey=SECRET", cache_ttl=300, timeout=10, logger=logger
            )
            url_source._wait_for_pending()
        logged = " ".join(str(c) for c in logger.error.call_args_list)
        self.assertNotIn("SECRET", logged)
        self.assertIn("e.com", logged)


class TestFetchUrlValue(unittest.TestCase):
    """Tests for the component-level entry point."""

    def setUp(self):
        reset_cache()

    def test_missing_url_returns_none(self):
        """A component with no url renders 'No data' rather than raising."""
        self.assertIsNone(fetch_url_value({"type": "url"}, mock_logger))

    def test_extracts_via_component_config(self):
        """json_path and regex from the component are applied to the body."""
        component = {
            "type": "url",
            "url": "http://e.com/a",
            "json_path": ".a.b",
            "regex": r"([0-9.]+)",
        }
        with mock.patch.object(
            url_source, "urlopen", return_value=_FakeResponse(b'{"a": {"b": "21.5C"}}')
        ):
            fetch_url_value(component, mock_logger)
            url_source._wait_for_pending()
            self.assertEqual(fetch_url_value(component, mock_logger), "21.5")

    def test_timeout_is_capped_at_max(self):
        """An over-large configured timeout is clamped to MAX_TIMEOUT."""
        component = {"type": "url", "url": "http://e.com/a", "timeout": 9999}
        with mock.patch.object(
            url_source, "urlopen", return_value=_FakeResponse(b"hi")
        ) as m:
            fetch_url_value(component, mock_logger)
            url_source._wait_for_pending()
            self.assertEqual(m.call_args.kwargs["timeout"], MAX_TIMEOUT)

    def test_invalid_ttl_falls_back_to_default(self):
        """A non-positive or non-integer cache_ttl does not crash the render."""
        component = {"type": "url", "url": "http://e.com/a", "cache_ttl": "soon"}
        with mock.patch.object(url_source, "urlopen", return_value=_FakeResponse(b"hi")):
            self.assertIsNone(fetch_url_value(component, mock_logger))
            url_source._wait_for_pending()
            self.assertEqual(fetch_url_value(component, mock_logger), "hi")


class TestPrefetch(unittest.TestCase):
    """Tests for the startup prefetch."""

    def setUp(self):
        reset_cache()

    def test_prefetches_every_url_component(self):
        """Each distinct url in the config is fetched once at startup."""
        config = {
            "dashboards": [
                {
                    "name": "d1",
                    "components": [
                        {"type": "url", "url": "http://e.com/a"},
                        {"type": "entity", "entity_name": "sensor.x"},
                    ],
                },
                {"name": "d2", "components": [{"type": "url", "url": "http://e.com/b"}]},
            ]
        }
        with mock.patch.object(
            url_source, "urlopen", return_value=_FakeResponse(b"hi")
        ) as m:
            prefetch(config, mock_logger)
            url_source._wait_for_pending()
            self.assertEqual(m.call_count, 2)

    def test_empty_config_does_nothing(self):
        """A config with no url components makes no requests."""
        with mock.patch.object(url_source, "urlopen") as m:
            prefetch({}, mock_logger)
            m.assert_not_called()
```

Add `from urllib.error import URLError` to the test imports.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/dev/projects/trmnl-url-source && uv run pytest tests/test_url_source.py -v`
Expected: FAIL — `ImportError: cannot import name 'get_url_text'`

- [ ] **Step 3: Write the implementation**

Add to `src/trmnl_server/url_source.py`. Note `urlopen` is imported into the module namespace (`from urllib.request import urlopen`) so tests can patch `url_source.urlopen`.

Key rules to hold to:
- `get_url_text` does the cache read, decides whether to submit, and returns — it never touches a `Future`'s result.
- The lock is held only around dict reads/writes, never across the HTTP call.
- `_fetch` records `attempted_at` in a `finally` so failures back off too, and clears its own in-flight entry.
- `MAX_BYTES + 1` is requested from `read()` so an over-long body can be detected and warned about before truncating to `MAX_BYTES`.

```python
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, wait
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

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
```

`_fetch`, `get_url_text`, `fetch_url_value`, `prefetch`, `reset_cache` and
`_wait_for_pending` follow. `_coerce_int(value, default, maximum=None)` is a small
helper for `cache_ttl`/`timeout` that rejects `bool`, non-`int` and non-positive
values with a warning and returns the default — mirroring how `components.py`
validates `hours` and `columns`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /home/dev/projects/trmnl-url-source && uv run pytest tests/test_url_source.py -v`
Expected: PASS. Then run the whole suite: `uv run pytest tests/ -v` — expected PASS, no regressions.

- [ ] **Step 5: Commit**

```bash
cd /home/dev/projects/trmnl-url-source
git add src/trmnl_server/url_source.py tests/test_url_source.py
git commit -m "feat: non-blocking cached fetching for URL sources"
```

---

### Task 3: Wire the component into config, models and rendering

**Files:**
- Modify: `src/trmnl_server/models.py`
- Modify: `src/trmnl_server/config.py`
- Modify: `src/trmnl_server/components.py`
- Modify: `src/trmnl_server/server.py`
- Test: `tests/test_config.py`, `tests/test_components.py`

**Interfaces:**
- Consumes: `fetch_url_value`, `prefetch`, `reset_cache`, `_wait_for_pending` from Task 2.
- Produces: a working `type: url` component end to end.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_config.py`:

```python
class TestUrlComponentValidation(unittest.TestCase):
    """Validation for the url component type."""

    def test_url_is_a_valid_component_type(self):
        """A well-formed url component produces no warnings."""
        logger = mock.Mock(spec=logging.Logger)
        config = {
            "dashboards": [
                {
                    "name": "d",
                    "components": [
                        {"type": "url", "url": "https://e.com/a", "friendly_name": "X"}
                    ],
                }
            ]
        }
        _validate_config(config, logger)
        logger.warning.assert_not_called()

    def test_missing_url_warns(self):
        """A url component without a url is flagged."""
        logger = mock.Mock(spec=logging.Logger)
        _validate_config(
            {"dashboards": [{"name": "d", "components": [{"type": "url"}]}]}, logger
        )
        self.assertTrue(logger.warning.called)

    def test_non_http_scheme_warns(self):
        """A file:// url is flagged at config load."""
        logger = mock.Mock(spec=logging.Logger)
        _validate_config(
            {
                "dashboards": [
                    {"name": "d", "components": [{"type": "url", "url": "file:///etc/passwd"}]}
                ]
            },
            logger,
        )
        self.assertTrue(logger.warning.called)

    def test_uncompilable_regex_warns(self):
        """A broken regex is caught at config load, not at render time."""
        logger = mock.Mock(spec=logging.Logger)
        _validate_config(
            {
                "dashboards": [
                    {
                        "name": "d",
                        "components": [
                            {"type": "url", "url": "https://e.com/a", "regex": "(["}
                        ],
                    }
                ]
            },
            logger,
        )
        self.assertTrue(logger.warning.called)

    def test_invalid_cache_ttl_warns(self):
        """A non-positive cache_ttl is flagged."""
        logger = mock.Mock(spec=logging.Logger)
        _validate_config(
            {
                "dashboards": [
                    {
                        "name": "d",
                        "components": [
                            {"type": "url", "url": "https://e.com/a", "cache_ttl": 0}
                        ],
                    }
                ]
            },
            logger,
        )
        self.assertTrue(logger.warning.called)

    def test_validation_warning_never_leaks_the_query_string(self):
        """Config warnings redact the url, like url_source's logs do."""
        logger = mock.Mock(spec=logging.Logger)
        _validate_config(
            {
                "dashboards": [
                    {
                        "name": "d",
                        "components": [
                            {"type": "url", "url": "https://e.com/a?apikey=SECRET", "regex": "(["}
                        ],
                    }
                ]
            },
            logger,
        )
        logged = " ".join(str(c) for c in logger.warning.call_args_list)
        self.assertNotIn("SECRET", logged)
```

Add to `tests/test_components.py`:

```python
class TestUrlComponentRendering(unittest.TestCase):
    """Integration: a url component through render_dashboard_image."""

    def setUp(self):
        url_source.reset_cache()

    def test_renders_extracted_value(self):
        """A warm cache renders the extracted text into the dashboard image."""
        dashboard = {
            "name": "d",
            "components": [
                {
                    "type": "url",
                    "friendly_name": "Price",
                    "url": "http://e.com/a",
                    "json_path": ".data.amount",
                }
            ],
        }
        with mock.patch.object(
            url_source, "urlopen", return_value=_FakeResponse(b'{"data": {"amount": "42"}}')
        ):
            render_dashboard_image(dashboard, mock_logger)   # cold: schedules the fetch
            url_source._wait_for_pending()
            img_io = render_dashboard_image(dashboard, mock_logger)
        self.assertIsNotNone(img_io)
        self.assertGreater(len(img_io.getvalue()), 0)

    def test_cold_render_does_not_block(self):
        """A slow endpoint does not delay the render thread."""
        dashboard = {
            "name": "d",
            "components": [
                {"type": "url", "friendly_name": "Price", "url": "http://e.com/a"}
            ],
        }
        with mock.patch.object(
            url_source, "urlopen", return_value=_FakeResponse(b"42", delay=3.0)
        ):
            t0 = time.perf_counter()
            render_dashboard_image(dashboard, mock_logger)
            elapsed = time.perf_counter() - t0
            url_source._wait_for_pending()
        self.assertLess(elapsed, 2.0, "render must not wait for a slow fetch")
```

`_FakeResponse` is duplicated into `tests/test_components.py` rather than shared —
the suite has no shared helper module and adding one is out of scope.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/dev/projects/trmnl-url-source && uv run pytest tests/test_config.py -k Url tests/test_components.py -k Url -v`
Expected: FAIL — the config warns "unknown type 'url'" and the render produces a "No data" panel that never resolves.

- [ ] **Step 3: Write the implementation**

`models.py` — extend `ComponentConfig`:

```python
    type: Literal["history_graph", "entity", "calendar", "entities", "todo_list", "url"]
    url: str
    json_path: str
    regex: str
    cache_ttl: int
    timeout: int
```

`config.py` — add `"url"` to `VALID_COMPONENT_TYPES`, and inside the existing
component loop in `_validate_config`, after the type check:

```python
            if ctype == "url":
                _validate_url_component(component, tag, j, logger)
```

with a module-level helper that **never echoes the url value** (no `%r`, no `%s`
for the URL — that is what makes this different from the surrounding validators):

```python
def _validate_url_component(
    component: "ComponentConfig",
    tag: str,
    index: int,
    logger: "Logger",
) -> None:
    """Warn about invalid fields on a url component.

    The url itself is never included in a warning: API keys are documented to
    live in its query string and warnings are written to a persisted log file.
    """
    url = component.get("url")
    if not url or not isinstance(url, str):
        logger.warning("config: %s component[%d] type 'url' is missing 'url'", tag, index)
    elif urlsplit(url).scheme not in ("http", "https"):
        logger.warning(
            "config: %s component[%d] 'url' must be an http or https URL", tag, index
        )

    pattern = component.get("regex")
    if pattern is not None:
        try:
            re.compile(pattern)
        except (re.error, TypeError) as e:
            logger.warning(
                "config: %s component[%d] 'regex' does not compile: %s", tag, index, e
            )

    for key in ("cache_ttl", "timeout"):
        value = component.get(key)
        if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value <= 0):
            logger.warning(
                "config: %s component[%d] '%s' must be a positive integer, got %r",
                tag, index, key, value,
            )
```

`components.py` — in `render_dashboard_image`, alongside the other branches:

```python
        elif component_type == 'url':
            from .url_source import fetch_url_value
            data = fetch_url_value(component, logger)
```

and in `_render_component`, change `elif component_type == 'entity':` to
`elif component_type in ('entity', 'url'):`.

`server.py` — in `main()`, before `httpd.serve_forever()`:

```python
            from .config import read_config
            from .url_source import prefetch
            prefetch(read_config(logger), logger)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /home/dev/projects/trmnl-url-source && uv run pytest tests/ -v`
Expected: PASS, including every pre-existing test. If `test_golden.py` fails, a
rendering change leaked in — investigate rather than regenerating goldens.

- [ ] **Step 5: Commit**

```bash
cd /home/dev/projects/trmnl-url-source
git add src/trmnl_server tests/test_config.py tests/test_components.py
git commit -m "feat: add url component type to config, models and rendering"
```

---

### Task 4: Golden image and end-to-end test

**Files:**
- Modify: `tests/test_golden.py`
- Create: `tests/test_url_source_e2e.py`
- Create: `tests/golden/url_panel.png` (generated)

**Interfaces:**
- Consumes: everything from Tasks 1-3.
- Produces: no new code interfaces.

- [ ] **Step 1: Write the golden test**

Add to `tests/test_golden.py`, following the existing tests' structure:

```python
    def test_url_panel(self):
        """A url component renders its extracted value like an entity panel."""
        url_source.reset_cache()
        dashboard = {
            "name": "url_panel",
            "title": "URL",
            "components": [
                {
                    "type": "url",
                    "friendly_name": "Bitcoin",
                    "url": "http://e.com/price",
                    "json_path": ".data.amount",
                }
            ],
        }
        with mock.patch.object(
            url_source, "urlopen", return_value=_FakeResponse(b'{"data": {"amount": "64231"}}')
        ):
            render_dashboard_image(dashboard, mock_logger, now=FIXED_NOW)
            url_source._wait_for_pending()
            with mock.patch("trmnl_server.components.datetime", mock_datetime("12:00")):
                img_io = render_dashboard_image(dashboard, mock_logger, now=FIXED_NOW)
        assert_golden(img_io, "url_panel")
```

Match the `now=` / `mock_datetime` handling used by the neighbouring golden tests
in that file — read them first and copy the pattern exactly, since the header
clock is what makes these byte-exact.

- [ ] **Step 2: Write the end-to-end test**

Create `tests/test_url_source_e2e.py` — a real localhost HTTP server, a real
`urlopen`, and the full `/api/display` → PNG flow, following the structure of
`tests/test_firmware_e2e.py` (read it first):

```python
"""End-to-end test for the url data source — real HTTP, no mocking.

Serves a JSON body from a real localhost http.server, then drives this
server's /static/<dashboard>.png route to prove the value reaches a rendered
image. Synchronised on the fetch executor via _wait_for_pending() rather than
sleeps, so it cannot flake.
"""
```

The test must:
1. Start a `ThreadingHTTPServer` on port 0 serving `{"data": {"amount": "64231"}}`.
2. Write a temp `config.yaml` with one device and one dashboard holding a `url`
   component pointing at that server, with `json_path: ".data.amount"`.
3. Start the trmnl server (as `test_firmware_e2e.py` does) with `CONFIG_PATH` set.
4. Request the dashboard PNG once — assert HTTP 200 (a cold cache renders the
   "No data" panel, which is still a valid image).
5. `url_source._wait_for_pending()`.
6. Request it again — assert HTTP 200 and that the PNG differs from the first
   response's bytes, proving the fetched value reached the render.
7. Assert the upstream server received exactly one request across both renders,
   proving the cache is doing its job.
8. Tear down both servers and call `url_source.reset_cache()`.

- [ ] **Step 3: Run both**

Run: `cd /home/dev/projects/trmnl-url-source && uv run pytest tests/test_golden.py tests/test_url_source_e2e.py -v`
Expected: the golden file is created on first run; the e2e test passes. Run the
golden test a second time to confirm it now compares equal rather than regenerating.

- [ ] **Step 4: Run the full suite**

Run: `cd /home/dev/projects/trmnl-url-source && uv run pytest tests/ -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/dev/projects/trmnl-url-source
git add tests/
git commit -m "test: golden and end-to-end coverage for url data source"
```

---

### Task 5: Documentation

**Files:**
- Modify: `README.md`
- Modify: `examples/config.yaml`
- Modify: `CHANGELOG.md`
- Modify: `AGENTS.md`

- [ ] **Step 1: README**

Add `url` to the component-types list and the features list, then a subsection
documenting every field (`url`, `json_path`, `regex`, `cache_ttl`, `timeout`)
with a worked example. It must state:
- Extraction order: `json_path` first, then `regex`, then raw body.
- Regex returns group 1 if the pattern has groups, else the whole match.
- Data is fetched in the background; a panel shows "No data" until its first
  fetch completes, and the last good value keeps rendering if the source goes down.
- **Known limitation:** prefetch runs at server startup, so a `url` component
  added to a running server's config shows "No data" until the next refresh cycle.
- **Auth:** put API keys in the query string; request headers are not
  configurable. URLs are redacted in logs so keys are not written to disk.

- [ ] **Step 2: examples/config.yaml**

Add a commented `url` component to a dashboard, in the style of the existing
commented `todo_list` example.

- [ ] **Step 3: CHANGELOG**

Add an entry under a new version heading, matching the existing format.

- [ ] **Step 4: AGENTS.md**

Add a line to "Component Notes" describing the `url` component's caching and
non-blocking behaviour, and add `url_source.py` to the Project Structure tree.

- [ ] **Step 5: Commit**

```bash
cd /home/dev/projects/trmnl-url-source
git add README.md examples/config.yaml CHANGELOG.md AGENTS.md
git commit -m "docs: document the url data source component"
```
