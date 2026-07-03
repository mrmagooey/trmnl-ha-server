"""Tests for firmware module."""

import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock
from urllib.error import URLError

from trmnl_server.firmware import (
    _download_asset,
    _failures,
    _fw_differs,
    _repo_dir_name,
    resolve_firmware,
)


class TestFwDiffers(unittest.TestCase):
    def test_strips_v_prefix_on_both_sides(self):
        self.assertFalse(_fw_differs("v1.6.0", "1.6.0"))

    def test_equal_without_prefix(self):
        self.assertFalse(_fw_differs("1.6.0", "1.6.0"))

    def test_different_versions(self):
        self.assertTrue(_fw_differs("1.5.2", "1.6.0"))


class TestRepoDirName(unittest.TestCase):
    def test_replaces_slash_with_underscore(self):
        self.assertEqual(_repo_dir_name("usetrmnl/firmware"), "usetrmnl_firmware")


class TestDownloadAsset(unittest.TestCase):
    def setUp(self):
        self.logger = mock.Mock()
        self.tmp = TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_success_writes_dest_file(self):
        dest = Path(self.tmp.name) / "sub" / "firmware.bin"
        cm = mock.MagicMock()
        cm.__enter__.return_value.read.return_value = b"payload"

        with mock.patch('trmnl_server.firmware.urlopen', return_value=cm):
            ok = _download_asset("https://example.com/firmware.bin", dest, self.logger)

        self.assertTrue(ok)
        self.assertEqual(dest.read_bytes(), b"payload")
        self.assertFalse((dest.parent / "firmware.bin.part").exists())

    def test_failure_cleans_up_partial_file(self):
        dest = Path(self.tmp.name) / "firmware.bin"

        with mock.patch('trmnl_server.firmware.urlopen', side_effect=URLError("boom")):
            ok = _download_asset("https://example.com/firmware.bin", dest, self.logger)

        self.assertFalse(ok)
        self.assertFalse(dest.exists())
        self.assertFalse((dest.parent / "firmware.bin.part").exists())


class TestResolveFirmware(unittest.TestCase):
    def setUp(self):
        self.logger = mock.Mock()
        self.tmp = TemporaryDirectory()
        self.cache_dir = self.tmp.name
        _failures.clear()

    def tearDown(self):
        self.tmp.cleanup()
        _failures.clear()

    def test_cache_hit_returns_existing_file_without_network_call(self):
        cache_root = Path(self.cache_dir) / "owner_repo" / "v1.0.0"
        cache_root.mkdir(parents=True)
        cached_file = cache_root / "firmware.bin"
        cached_file.write_bytes(b"binary-data")

        with mock.patch('trmnl_server.firmware.urlopen') as mock_urlopen:
            result = resolve_firmware("owner/repo", "v1.0.0", "*.bin", self.cache_dir, self.logger)

        self.assertEqual(result, cached_file)
        mock_urlopen.assert_not_called()

    def test_cache_hit_ignores_partial_downloads(self):
        cache_root = Path(self.cache_dir) / "owner_repo" / "v1.0.0"
        cache_root.mkdir(parents=True)
        (cache_root / "firmware.bin.part").write_bytes(b"incomplete")
        release_cm = mock.MagicMock()
        release_cm.__enter__.return_value.read.return_value = (
            b'{"assets": [{"name": "firmware.bin", "browser_download_url": "https://example.com/firmware.bin"}]}'
        )
        download_cm = mock.MagicMock()
        download_cm.__enter__.return_value.read.return_value = b"binary-data"

        with mock.patch('trmnl_server.firmware.urlopen', side_effect=[release_cm, download_cm]):
            result = resolve_firmware("owner/repo", "v1.0.0", "*.bin", self.cache_dir, self.logger)

        self.assertEqual(result.name, "firmware.bin")

    def test_downloads_and_caches_matching_asset(self):
        release_cm = mock.MagicMock()
        release_cm.__enter__.return_value.read.return_value = (
            b'{"assets": [{"name": "firmware.bin", "browser_download_url": "https://example.com/firmware.bin"}]}'
        )
        download_cm = mock.MagicMock()
        download_cm.__enter__.return_value.read.return_value = b"binary-data"

        with mock.patch('trmnl_server.firmware.urlopen', side_effect=[release_cm, download_cm]) as mock_urlopen:
            result = resolve_firmware("owner/repo", "v1.0.0", "*.bin", self.cache_dir, self.logger)

        self.assertEqual(mock_urlopen.call_count, 2)
        self.assertEqual(result.name, "firmware.bin")
        self.assertEqual(result.read_bytes(), b"binary-data")

    def test_latest_version_hits_the_latest_endpoint(self):
        release_cm = mock.MagicMock()
        release_cm.__enter__.return_value.read.return_value = (
            b'{"assets": [{"name": "firmware.bin", "browser_download_url": "https://example.com/firmware.bin"}]}'
        )
        download_cm = mock.MagicMock()
        download_cm.__enter__.return_value.read.return_value = b"binary-data"

        with mock.patch('trmnl_server.firmware.urlopen', side_effect=[release_cm, download_cm]) as mock_urlopen:
            resolve_firmware("owner/repo", "latest", "*.bin", self.cache_dir, self.logger)

        first_request = mock_urlopen.call_args_list[0].args[0]
        self.assertEqual(first_request.full_url, "https://api.github.com/repos/owner/repo/releases/latest")

    def test_pinned_version_hits_the_tags_endpoint(self):
        release_cm = mock.MagicMock()
        release_cm.__enter__.return_value.read.return_value = b'{"assets": []}'

        with mock.patch('trmnl_server.firmware.urlopen', return_value=release_cm) as mock_urlopen:
            resolve_firmware("owner/repo", "v1.6.0", "*.bin", self.cache_dir, self.logger)

        first_request = mock_urlopen.call_args_list[0].args[0]
        self.assertEqual(first_request.full_url, "https://api.github.com/repos/owner/repo/releases/tags/v1.6.0")

    def test_no_matching_asset_returns_none(self):
        release_cm = mock.MagicMock()
        release_cm.__enter__.return_value.read.return_value = (
            b'{"assets": [{"name": "other.txt", "browser_download_url": "https://example.com/other.txt"}]}'
        )

        with mock.patch('trmnl_server.firmware.urlopen', return_value=release_cm):
            result = resolve_firmware("owner/repo", "v1.0.0", "*.bin", self.cache_dir, self.logger)

        self.assertIsNone(result)
        self.logger.warning.assert_called()

    def test_network_failure_returns_none(self):
        with mock.patch('trmnl_server.firmware.urlopen', side_effect=URLError("boom")):
            result = resolve_firmware("owner/repo", "v1.0.0", "*.bin", self.cache_dir, self.logger)

        self.assertIsNone(result)

    def test_failure_is_cached_within_cooldown(self):
        with mock.patch('trmnl_server.firmware.urlopen', side_effect=URLError("boom")) as mock_urlopen:
            resolve_firmware("owner/repo", "v1.0.0", "*.bin", self.cache_dir, self.logger)
            result = resolve_firmware("owner/repo", "v1.0.0", "*.bin", self.cache_dir, self.logger)

        self.assertIsNone(result)
        mock_urlopen.assert_called_once()

    def test_failure_cooldown_expires(self):
        with mock.patch('trmnl_server.firmware.urlopen', side_effect=URLError("boom")) as mock_urlopen:
            resolve_firmware("owner/repo", "v1.0.0", "*.bin", self.cache_dir, self.logger)
            with mock.patch('trmnl_server.firmware.time.time', return_value=time.time() + 301):
                resolve_firmware("owner/repo", "v1.0.0", "*.bin", self.cache_dir, self.logger)

        self.assertEqual(mock_urlopen.call_count, 2)


if __name__ == '__main__':
    unittest.main()
