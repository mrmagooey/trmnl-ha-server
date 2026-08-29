"""Unit tests for the URL data source module."""

import logging
import time
import unittest
from unittest import mock
from urllib.error import URLError

from trmnl_server import url_source
from trmnl_server.url_source import (
    MAX_BYTES,
    MAX_TIMEOUT,
    _json_path,
    _redact,
    _stringify,
    extract_value,
    fetch_url_value,
    get_url_text,
    prefetch,
    reset_cache,
)

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

    def test_dangling_bracket_returns_none(self):
        """A path ending in an unclosed bracket is malformed, not ignored."""
        self.assertIsNone(_json_path({"a": [1]}, ".a["))

    def test_dangling_bracket_after_index_returns_none(self):
        """A trailing unclosed bracket after a valid index is still malformed."""
        self.assertIsNone(_json_path({"a": [[9, 8]]}, ".a[0]["))

    def test_empty_brackets_return_none(self):
        """An empty index is malformed."""
        self.assertIsNone(_json_path({"a": [1]}, ".a[]"))


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
