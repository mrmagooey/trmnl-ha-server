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
