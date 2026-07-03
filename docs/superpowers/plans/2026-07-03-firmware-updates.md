# Self-hosted Firmware Update Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `trmnl-ha-server` resolve and cache firmware binaries from a configured GitHub releases repo, and serve them through `/api/display`'s `update_firmware`/`firmware_url` fields instead of always returning `false`/`null`.

**Architecture:** A new `firmware.py` module resolves a `(repo, version, asset_pattern)` triple to a locally cached binary file, downloading from the GitHub REST API on first use and caching to disk thereafter. `api.py`'s `_handle_api_display` compares the device's `FW-Version` header against the configured target version and, on mismatch, asks `firmware.py` to resolve the binary; a new `/static/firmware/<version>/<filename>` route serves the cached bytes. Config gains an optional top-level `firmware:` block and an optional per-device `firmware_asset_pattern` override.

**Tech Stack:** Python 3.12 stdlib only — `urllib.request` for the GitHub API (matching `hass_client.py`'s existing pattern), `pathlib`, `fnmatch`, `threading`. No new dependencies.

## Global Constraints

- No new third-party dependencies — `urllib.request` only, matching `hass_client.py`'s existing HTTP pattern (`Request`/`urlopen`, `HTTPError`/`URLError` handling).
- All new/modified public and private helpers use full type annotations, matching the rest of the codebase.
- Follow existing test conventions exactly: `unittest.TestCase`, `unittest.mock.patch('trmnl_server.<module>.<name>')` targeting the *importing* module's namespace (not the defining module), and the `APICalls.__new__(APICalls)` handler-construction helper already used in `tests/test_api.py`.
- `firmware:` config block is entirely optional; its absence must leave `/api/display` behavior byte-for-byte identical to today (`update_firmware: false`, `firmware_url: null`).
- Any firmware-resolution failure (bad repo, missing tag, network error, no matching asset) must degrade to `update_firmware: false` / `firmware_url: null` and a logged warning — it must never raise out of `_handle_api_display` or break dashboard serving.
- Env var: `FIRMWARE_CACHE_DIR`, default `"firmware_cache"` (relative path, matching `CONFIG_PATH`'s existing convention).

---

### Task 1: Config schema — `firmware:` block and per-device override

**Files:**
- Modify: `src/trmnl_server/models.py`
- Modify: `src/trmnl_server/config.py`
- Test: `tests/test_config.py`
- Modify (docs, no test): `examples/config.yaml`

**Interfaces:**
- Produces: `models.FirmwareConfig` (`TypedDict`, keys `repo: str`, `version: str`, `asset_pattern: str`, all required within the dict but the dict itself is optional on `Config`). `models.DeviceConfig` gains optional key `firmware_asset_pattern: str`. `models.Config` gains optional key `firmware: FirmwareConfig`.
- Consumes: nothing from other tasks.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_config.py`, inside a new test class placed after `TestFindDevice` and before `TestAlignedRefreshRate` (the file already imports `unittest`, `mock`, `datetime`/`timedelta`, and the `read_config`-adjacent helpers — no new imports needed since this only calls the module-private `_validate_config`):

```python
class TestValidateFirmwareConfig(unittest.TestCase):
    """Tests for the 'firmware' block validation in _validate_config."""

    def setUp(self):
        self.mock_logger = mock.Mock()

    def test_no_firmware_key_is_valid(self):
        from trmnl_server.config import _validate_config
        _validate_config({'devices': [], 'dashboards': []}, self.mock_logger)
        self.mock_logger.warning.assert_not_called()

    def test_complete_firmware_block_is_valid(self):
        from trmnl_server.config import _validate_config
        config = {
            'firmware': {'repo': 'owner/repo', 'version': 'v1.6.0', 'asset_pattern': '*.bin'},
        }
        _validate_config(config, self.mock_logger)
        self.mock_logger.warning.assert_not_called()

    def test_firmware_not_a_mapping_warns(self):
        from trmnl_server.config import _validate_config
        _validate_config({'firmware': 'not-a-dict'}, self.mock_logger)
        self.mock_logger.warning.assert_called_once()

    def test_firmware_missing_repo_warns(self):
        from trmnl_server.config import _validate_config
        config = {'firmware': {'version': 'v1.6.0', 'asset_pattern': '*.bin'}}
        _validate_config(config, self.mock_logger)
        self.mock_logger.warning.assert_called_once_with(
            "config: 'firmware.%s' missing or invalid", 'repo'
        )

    def test_firmware_missing_version_warns(self):
        from trmnl_server.config import _validate_config
        config = {'firmware': {'repo': 'owner/repo', 'asset_pattern': '*.bin'}}
        _validate_config(config, self.mock_logger)
        self.mock_logger.warning.assert_called_once_with(
            "config: 'firmware.%s' missing or invalid", 'version'
        )

    def test_firmware_missing_asset_pattern_warns(self):
        from trmnl_server.config import _validate_config
        config = {'firmware': {'repo': 'owner/repo', 'version': 'v1.6.0'}}
        _validate_config(config, self.mock_logger)
        self.mock_logger.warning.assert_called_once_with(
            "config: 'firmware.%s' missing or invalid", 'asset_pattern'
        )

    def test_firmware_non_string_value_warns(self):
        from trmnl_server.config import _validate_config
        config = {'firmware': {'repo': 123, 'version': 'v1.6.0', 'asset_pattern': '*.bin'}}
        _validate_config(config, self.mock_logger)
        self.mock_logger.warning.assert_called_once_with(
            "config: 'firmware.%s' missing or invalid", 'repo'
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_config.py::TestValidateFirmwareConfig -v`
Expected: FAIL — `test_no_firmware_key_is_valid` and `test_complete_firmware_block_is_valid` pass trivially (no validation exists yet so no warnings fire either way), but `test_firmware_not_a_mapping_warns`, `test_firmware_missing_repo_warns`, `test_firmware_missing_version_warns`, `test_firmware_missing_asset_pattern_warns`, and `test_firmware_non_string_value_warns` FAIL with `AssertionError: Expected 'warning' to have been called once. Called 0 times.` (validation doesn't exist yet, so no warnings are logged).

- [ ] **Step 3: Add `FirmwareConfig` and the new optional keys to `models.py`**

In `src/trmnl_server/models.py`, replace:

```python
class DeviceConfig(TypedDict, total=False):
    """Per-device configuration."""
    id: Required[str]
    name: str
    sleep_start: str
    sleep_end: str
    rotate: int
    schedule: list[ScheduleEntry]


class Config(TypedDict, total=False):
    """Root configuration structure."""
    devices: list[DeviceConfig]
    dashboards: list[DashboardConfig]
```

with:

```python
class DeviceConfig(TypedDict, total=False):
    """Per-device configuration."""
    id: Required[str]
    name: str
    sleep_start: str
    sleep_end: str
    rotate: int
    schedule: list[ScheduleEntry]
    firmware_asset_pattern: str


class FirmwareConfig(TypedDict, total=False):
    """Configuration for self-hosted firmware update delivery."""
    repo: str
    version: str
    asset_pattern: str


class Config(TypedDict, total=False):
    """Root configuration structure."""
    devices: list[DeviceConfig]
    dashboards: list[DashboardConfig]
    firmware: FirmwareConfig
```

- [ ] **Step 4: Add firmware validation to `_validate_config` in `config.py`**

In `src/trmnl_server/config.py`, insert this block immediately before the line `dashboards = config.get("dashboards")` (currently line 130, right after the closing of the `devices` validation block):

```python
    firmware = config.get("firmware")
    if firmware is not None:
        if not isinstance(firmware, dict):
            logger.warning("config: 'firmware' must be a mapping")
        else:
            for key in ("repo", "version", "asset_pattern"):
                value = firmware.get(key)
                if not value or not isinstance(value, str):
                    logger.warning("config: 'firmware.%s' missing or invalid", key)

```

Also update the `_validate_config` import in `config.py`'s own imports — no change needed there since `_validate_config` already takes the whole `Config` dict; just update its type-hinted parameter usage is unaffected (it's typed as `Config` already, and `Config` now includes `firmware`).

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_config.py::TestValidateFirmwareConfig -v`
Expected: PASS (7 passed)

- [ ] **Step 6: Document the new config in `examples/config.yaml`**

In `examples/config.yaml`, add a comment + optional key to the first device entry. Find:

```yaml
    id: "AA:BB:CC:DD:EE:FF"
    # Optional human-readable name for this device (used in log messages).
    name: "Living Room"
```

Replace with:

```yaml
    id: "AA:BB:CC:DD:EE:FF"
    # Optional human-readable name for this device (used in log messages).
    name: "Living Room"

    # Optional: overrides the top-level firmware.asset_pattern for this device.
    # Use when different physical devices need different board-variant binaries
    # from the same GitHub release (e.g. a Seeed Studio build vs. the official
    # TRMNL PCB build).
    # firmware_asset_pattern: "*seeed_xiao_esp32c3*.bin"
```

Then append a new top-level section at the end of the file (after the last dashboard's components, i.e. after the final `type: entity` block):

```yaml

# Optional: self-hosted firmware update delivery. When present, /api/display
# compares each device's FW-Version request header against `version`; on a
# mismatch, the server fetches the matching release asset from GitHub
# (caching it to disk on first use) and tells the device to update.
# firmware:
#   # GitHub "owner/repo" to pull releases from.
#   repo: usetrmnl/firmware
#   # Exact release tag (e.g. "v1.6.0"), or "latest".
#   version: v1.6.0
#   # Default glob (fnmatch) used to pick the release asset by filename, when
#   # a device doesn't set its own firmware_asset_pattern.
#   asset_pattern: "*.bin"
```

- [ ] **Step 7: Commit**

```bash
git add src/trmnl_server/models.py src/trmnl_server/config.py tests/test_config.py examples/config.yaml
git commit -m "feat: add firmware config schema and validation"
```

---

### Task 2: `firmware.py` — resolve and cache a GitHub release asset

**Files:**
- Create: `src/trmnl_server/firmware.py`
- Test: `tests/test_firmware.py`

**Interfaces:**
- Consumes: nothing from Task 1 (this module has no dependency on `models.py` or `config.py` — it takes plain strings).
- Produces:
  - `firmware.FIRMWARE_CACHE_DIR: str` — module-level constant, `environ.get("FIRMWARE_CACHE_DIR", "firmware_cache")`.
  - `firmware._fw_differs(current: str, target: str) -> bool`
  - `firmware.resolve_firmware(repo: str, version: str, asset_pattern: str, cache_dir: str, logger: "Logger") -> Path | None`
  - `firmware._repo_dir_name(repo: str) -> str` (used by Task 3's static route handler to build the same cache path).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_firmware.py`:

```python
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
            b'{"assets": [{"name": "other.bin", "browser_download_url": "https://example.com/other.bin"}]}'
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_firmware.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'trmnl_server.firmware'` (or `ImportError`, since the module doesn't exist yet).

- [ ] **Step 3: Write the implementation**

Create `src/trmnl_server/firmware.py`:

```python
"""Self-hosted firmware update delivery for trmnl-server.

Resolves a target GitHub release to a locally cached firmware binary,
downloading and caching it to disk on first use.
"""

import json
import threading
import time
from fnmatch import fnmatch
from os import environ, replace as os_replace
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

if TYPE_CHECKING:
    from logging import Logger

FIRMWARE_CACHE_DIR: str = environ.get("FIRMWARE_CACHE_DIR", "firmware_cache")

# How long to remember a failed resolution before retrying GitHub, so a
# misconfigured repo/version/pattern doesn't get hit on every device poll.
_FAILURE_COOLDOWN_SECONDS: int = 300

_lock: threading.Lock = threading.Lock()
_failures: dict[tuple[str, str, str], float] = {}

_USER_AGENT: str = "trmnl-server-firmware-updater"


def _fw_differs(current: str, target: str) -> bool:
    """True if a device's current firmware version differs from the target.

    Strips a leading 'v'/'V' from both sides before comparing, since GitHub
    release tags are conventionally prefixed (e.g. 'v1.6.0') while devices
    report bare version strings (e.g. '1.6.0').
    """
    return current.lstrip('vV') != target.lstrip('vV')


def _repo_dir_name(repo: str) -> str:
    """Filesystem-safe cache subdirectory name for an 'owner/repo' string."""
    return repo.replace('/', '_')


def _fetch_release_assets(repo: str, version: str, logger: "Logger") -> list[dict] | None:
    """Fetch the asset list for a GitHub release.

    Args:
        repo: "owner/repo".
        version: Exact release tag, or "latest".
        logger: Logger for warnings.

    Returns:
        The release's assets (each a dict with at least 'name' and
        'browser_download_url'), or None on any failure.
    """
    if version == "latest":
        url = f"https://api.github.com/repos/{repo}/releases/latest"
    else:
        url = f"https://api.github.com/repos/{repo}/releases/tags/{version}"

    req = Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": _USER_AGENT,
    })
    try:
        with urlopen(req, timeout=10) as response:
            data: dict = json.loads(response.read().decode())
            return data.get("assets", [])
    except HTTPError as e:
        logger.warning("GitHub release lookup failed for %s@%s: %d %s", repo, version, e.code, e.reason)
        return None
    except URLError as e:
        logger.warning("GitHub release lookup failed for %s@%s: %s", repo, version, e.reason)
        return None


def _download_asset(download_url: str, dest: Path, logger: "Logger") -> bool:
    """Download a release asset to `dest`, atomically (temp file + rename).

    Returns:
        True on success, False on any failure (dest is left untouched).
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path = dest.parent / f"{dest.name}.part"
    req = Request(download_url, headers={"User-Agent": _USER_AGENT})
    try:
        with urlopen(req, timeout=30) as response:
            tmp_path.write_bytes(response.read())
        os_replace(tmp_path, dest)
        return True
    except (HTTPError, URLError) as e:
        logger.warning("Failed to download firmware asset from %s: %s", download_url, e)
        tmp_path.unlink(missing_ok=True)
        return False


def resolve_firmware(
    repo: str,
    version: str,
    asset_pattern: str,
    cache_dir: str,
    logger: "Logger",
) -> Path | None:
    """Return a local path to the release asset matching `asset_pattern`,
    downloading and caching it to disk on first use.

    Args:
        repo: GitHub "owner/repo" to pull the release from.
        version: Exact release tag (e.g. "v1.6.0"), or "latest".
        asset_pattern: fnmatch glob used to select the release asset by filename.
        cache_dir: Root directory for the on-disk firmware cache.
        logger: Logger for warnings.

    Returns:
        Path to the cached binary, or None if it could not be resolved
        (network failure, missing tag, or no asset matches the pattern).
        A failed resolution is remembered for 5 minutes, during which further
        calls with the same (repo, version, asset_pattern) return None
        immediately without contacting GitHub again.
    """
    cache_key = (repo, version, asset_pattern)

    with _lock:
        cache_root = Path(cache_dir) / _repo_dir_name(repo) / version

        if cache_root.is_dir():
            for existing in cache_root.iterdir():
                if not existing.name.endswith(".part") and fnmatch(existing.name, asset_pattern):
                    return existing

        failed_at = _failures.get(cache_key)
        if failed_at is not None and time.time() - failed_at < _FAILURE_COOLDOWN_SECONDS:
            return None

        assets = _fetch_release_assets(repo, version, logger)
        if assets is None:
            _failures[cache_key] = time.time()
            return None

        match = next((a for a in assets if fnmatch(a.get("name", ""), asset_pattern)), None)
        if match is None:
            logger.warning("No release asset matching %r found for %s@%s", asset_pattern, repo, version)
            _failures[cache_key] = time.time()
            return None

        dest = cache_root / match["name"]
        if not _download_asset(match["browser_download_url"], dest, logger):
            _failures[cache_key] = time.time()
            return None

        _failures.pop(cache_key, None)
        return dest
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_firmware.py -v`
Expected: PASS (13 passed)

- [ ] **Step 5: Commit**

```bash
git add src/trmnl_server/firmware.py tests/test_firmware.py
git commit -m "feat: add firmware.py — resolve and cache GitHub release binaries"
```

---

### Task 3: Wire firmware fields into `/api/display` and add the static firmware route

**Files:**
- Modify: `src/trmnl_server/api.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: `models.FirmwareConfig`, `DeviceConfig.firmware_asset_pattern` (Task 1); `firmware.resolve_firmware`, `firmware._fw_differs`, `firmware._repo_dir_name`, `firmware.FIRMWARE_CACHE_DIR` (Task 2).
- Produces: `APICalls._handle_static_firmware(self) -> bool`, and updated `_handle_api_display` behavior (`update_firmware`/`firmware_url` fields reflect real resolution instead of hardcoded `False`/`None`). Also re-exports `resolve_firmware` and `FIRMWARE_CACHE_DIR` into the `trmnl_server.api` namespace via the import (needed so tests can `mock.patch('trmnl_server.api.resolve_firmware', ...)` and `mock.patch('trmnl_server.api.FIRMWARE_CACHE_DIR', ...)`, matching this codebase's existing convention of importing helpers by name into `api.py` — see the existing `from .config import ... _aligned_refresh_rate, _seconds_until_next_visible` line).

- [ ] **Step 1: Write the failing tests**

Add these imports to the top of `tests/test_api.py` (it currently has `unittest`, `unittest.mock as mock`, `io.BytesIO`, `json`, and imports `api`/`APICalls`):

```python
from pathlib import Path
from tempfile import TemporaryDirectory
```

Then add these two new test classes at the end of the file, before the `if __name__ == '__main__':` block:

```python
class TestAPIFirmware(unittest.TestCase):
    """Integration tests for firmware fields in /api/display."""

    def setUp(self):
        api._device_indices.clear()

    def create_handler(self, path, headers=None):
        mock_logger = mock.Mock()
        handler = APICalls.__new__(APICalls)
        handler.logger = mock_logger
        handler.refresh_rate = 600
        handler.path = path
        handler.headers = headers or {}
        handler.client_address = ('127.0.0.1', 12345)
        handler.wfile = BytesIO()
        handler._response_code = None

        def mock_send_response(code):
            handler._response_code = code
        handler.send_response = mock_send_response
        handler.send_header = mock.Mock()
        handler.end_headers = mock.Mock()
        return handler

    @mock.patch('trmnl_server.api.resolve_firmware')
    @mock.patch('trmnl_server.api.read_config')
    def test_display_sets_update_firmware_when_versions_differ(self, mock_read_config, mock_resolve):
        mock_read_config.return_value = {
            'devices': [{'id': 'AA:BB:CC:DD:EE:FF'}],
            'dashboards': [],
            'firmware': {'repo': 'owner/repo', 'version': 'v1.6.0', 'asset_pattern': '*.bin'},
        }
        mock_resolve.return_value = Path('/cache/owner_repo/v1.6.0/firmware.bin')
        handler = self.create_handler('/api/display', {'ID': 'AA:BB:CC:DD:EE:FF', 'FW-Version': '1.5.2'})
        handler._handle_api_display()

        handler.wfile.seek(0)
        response = json.loads(handler.wfile.read().decode())

        self.assertTrue(response['update_firmware'])
        self.assertIn('/static/firmware/v1.6.0/firmware.bin', response['firmware_url'])
        mock_resolve.assert_called_once_with(
            'owner/repo', 'v1.6.0', '*.bin', api.FIRMWARE_CACHE_DIR, handler.logger
        )

    @mock.patch('trmnl_server.api.resolve_firmware')
    @mock.patch('trmnl_server.api.read_config')
    def test_display_no_update_when_versions_match(self, mock_read_config, mock_resolve):
        mock_read_config.return_value = {
            'devices': [{'id': 'AA:BB:CC:DD:EE:FF'}],
            'dashboards': [],
            'firmware': {'repo': 'owner/repo', 'version': 'v1.6.0', 'asset_pattern': '*.bin'},
        }
        handler = self.create_handler('/api/display', {'ID': 'AA:BB:CC:DD:EE:FF', 'FW-Version': 'v1.6.0'})
        handler._handle_api_display()

        handler.wfile.seek(0)
        response = json.loads(handler.wfile.read().decode())

        self.assertFalse(response['update_firmware'])
        self.assertIsNone(response['firmware_url'])
        mock_resolve.assert_not_called()

    @mock.patch('trmnl_server.api.resolve_firmware')
    @mock.patch('trmnl_server.api.read_config')
    def test_display_no_firmware_config_leaves_fields_false(self, mock_read_config, mock_resolve):
        mock_read_config.return_value = {
            'devices': [{'id': 'AA:BB:CC:DD:EE:FF'}],
            'dashboards': [],
        }
        handler = self.create_handler('/api/display', {'ID': 'AA:BB:CC:DD:EE:FF', 'FW-Version': '1.0.0'})
        handler._handle_api_display()

        handler.wfile.seek(0)
        response = json.loads(handler.wfile.read().decode())

        self.assertFalse(response['update_firmware'])
        self.assertIsNone(response['firmware_url'])
        mock_resolve.assert_not_called()

    @mock.patch('trmnl_server.api.resolve_firmware')
    @mock.patch('trmnl_server.api.read_config')
    def test_display_resolution_failure_degrades_gracefully(self, mock_read_config, mock_resolve):
        mock_read_config.return_value = {
            'devices': [{'id': 'AA:BB:CC:DD:EE:FF'}],
            'dashboards': [],
            'firmware': {'repo': 'owner/repo', 'version': 'v1.6.0', 'asset_pattern': '*.bin'},
        }
        mock_resolve.return_value = None
        handler = self.create_handler('/api/display', {'ID': 'AA:BB:CC:DD:EE:FF', 'FW-Version': '1.5.2'})
        handler._handle_api_display()

        handler.wfile.seek(0)
        response = json.loads(handler.wfile.read().decode())

        self.assertFalse(response['update_firmware'])
        self.assertIsNone(response['firmware_url'])
        self.assertEqual(handler._response_code, 200)

    @mock.patch('trmnl_server.api.resolve_firmware')
    @mock.patch('trmnl_server.api.read_config')
    def test_per_device_asset_pattern_overrides_global_default(self, mock_read_config, mock_resolve):
        mock_read_config.return_value = {
            'devices': [{'id': 'AA:BB:CC:DD:EE:FF', 'firmware_asset_pattern': '*seeed*.bin'}],
            'dashboards': [],
            'firmware': {'repo': 'owner/repo', 'version': 'v1.6.0', 'asset_pattern': '*.bin'},
        }
        mock_resolve.return_value = Path('/cache/owner_repo/v1.6.0/seeed_xiao.bin')
        handler = self.create_handler('/api/display', {'ID': 'AA:BB:CC:DD:EE:FF', 'FW-Version': '1.5.2'})
        handler._handle_api_display()

        mock_resolve.assert_called_once_with(
            'owner/repo', 'v1.6.0', '*seeed*.bin', api.FIRMWARE_CACHE_DIR, handler.logger
        )

    def test_no_fw_version_header_leaves_fields_false(self):
        with mock.patch('trmnl_server.api.read_config') as mock_read_config, \
             mock.patch('trmnl_server.api.resolve_firmware') as mock_resolve:
            mock_read_config.return_value = {
                'devices': [{'id': 'AA:BB:CC:DD:EE:FF'}],
                'dashboards': [],
                'firmware': {'repo': 'owner/repo', 'version': 'v1.6.0', 'asset_pattern': '*.bin'},
            }
            handler = self.create_handler('/api/display', {'ID': 'AA:BB:CC:DD:EE:FF'})
            handler._handle_api_display()

            handler.wfile.seek(0)
            response = json.loads(handler.wfile.read().decode())

        self.assertFalse(response['update_firmware'])
        mock_resolve.assert_not_called()


class TestStaticFirmwareRoute(unittest.TestCase):
    """Tests for GET /static/firmware/<version>/<filename>."""

    def create_handler(self, path, headers=None):
        mock_logger = mock.Mock()
        handler = APICalls.__new__(APICalls)
        handler.logger = mock_logger
        handler.refresh_rate = 600
        handler.path = path
        handler.headers = headers or {}
        handler.client_address = ('127.0.0.1', 12345)
        handler.wfile = BytesIO()
        handler._response_code = None
        handler._headers_sent = {}

        def mock_send_response(code):
            handler._response_code = code
        handler.send_response = mock_send_response

        def mock_send_header(key, value):
            handler._headers_sent[key] = value
        handler.send_header = mock_send_header
        handler.end_headers = mock.Mock()
        return handler

    @mock.patch('trmnl_server.api.read_config')
    def test_serves_cached_file_bytes(self, mock_read_config):
        with TemporaryDirectory() as cache_dir:
            mock_read_config.return_value = {
                'firmware': {'repo': 'owner/repo', 'version': 'v1.6.0', 'asset_pattern': '*.bin'}
            }
            fw_dir = Path(cache_dir) / 'owner_repo' / 'v1.6.0'
            fw_dir.mkdir(parents=True)
            (fw_dir / 'firmware.bin').write_bytes(b'binary-data')

            with mock.patch('trmnl_server.api.FIRMWARE_CACHE_DIR', cache_dir):
                handler = self.create_handler('/static/firmware/v1.6.0/firmware.bin')
                result = handler._handle_static_firmware()

            self.assertTrue(result)
            self.assertEqual(handler._response_code, 200)
            self.assertEqual(handler._headers_sent['Content-type'], 'application/octet-stream')
            handler.wfile.seek(0)
            self.assertEqual(handler.wfile.read(), b'binary-data')

    @mock.patch('trmnl_server.api.read_config')
    def test_missing_file_returns_false(self, mock_read_config):
        with TemporaryDirectory() as cache_dir:
            mock_read_config.return_value = {
                'firmware': {'repo': 'owner/repo', 'version': 'v1.6.0', 'asset_pattern': '*.bin'}
            }
            with mock.patch('trmnl_server.api.FIRMWARE_CACHE_DIR', cache_dir):
                handler = self.create_handler('/static/firmware/v1.6.0/missing.bin')
                result = handler._handle_static_firmware()

        self.assertFalse(result)

    @mock.patch('trmnl_server.api.read_config')
    def test_path_traversal_rejected(self, mock_read_config):
        mock_read_config.return_value = {
            'firmware': {'repo': 'owner/repo', 'version': 'v1.6.0', 'asset_pattern': '*.bin'}
        }
        handler = self.create_handler('/static/firmware/../secret')
        result = handler._handle_static_firmware()
        self.assertFalse(result)

    def test_no_firmware_config_returns_false(self):
        with mock.patch('trmnl_server.api.read_config', return_value={}):
            handler = self.create_handler('/static/firmware/v1.6.0/firmware.bin')
            result = handler._handle_static_firmware()
        self.assertFalse(result)

    def test_route_registered_in_do_get(self):
        with TemporaryDirectory() as cache_dir:
            fw_dir = Path(cache_dir) / 'owner_repo' / 'v1.6.0'
            fw_dir.mkdir(parents=True)
            (fw_dir / 'firmware.bin').write_bytes(b'binary-data')
            with mock.patch(
                'trmnl_server.api.read_config',
                return_value={'firmware': {'repo': 'owner/repo', 'version': 'v1.6.0', 'asset_pattern': '*.bin'}},
            ), mock.patch('trmnl_server.api.FIRMWARE_CACHE_DIR', cache_dir):
                handler = self.create_handler('/static/firmware/v1.6.0/firmware.bin')
                handler.do_GET()

        self.assertEqual(handler._response_code, 200)

    def test_unknown_firmware_path_falls_through_to_404(self):
        with mock.patch('trmnl_server.api.read_config', return_value={}):
            handler = self.create_handler('/static/firmware/v1.6.0/firmware.bin')
            handler.do_GET()
        self.assertEqual(handler._response_code, 404)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_api.py::TestAPIFirmware tests/test_api.py::TestStaticFirmwareRoute -v`
Expected: FAIL — `AttributeError: module 'trmnl_server.api' has no attribute 'resolve_firmware'` (or `FIRMWARE_CACHE_DIR`), and `AttributeError: 'APICalls' object has no attribute '_handle_static_firmware'`.

- [ ] **Step 3: Update imports in `api.py`**

In `src/trmnl_server/api.py`, replace the import block (current lines 6–29):

```python
import http.server
import json
import threading
import time
from io import BytesIO, SEEK_END
from os import environ
from typing import TYPE_CHECKING
from urllib.parse import quote

from .models import APIDisplayResponse, APISetupResponse, DashboardConfig, DeviceConfig, ScheduleEntry, RenderData
from .state import server_state
from .components import (
    render_dashboard_image,
    _create_info_image,
    eink_display,
    tile_components,
)
from .config import read_config, is_schedule_entry_visible, find_device, _coerce_time, _aligned_refresh_rate, _seconds_until_next_visible
from .hass_client import HASS_URL, HASS_TOKEN

if TYPE_CHECKING:
    from logging import Logger

SERVER_NAME: str = environ.get("SERVER_NAME", "https://www.example.com")
```

with:

```python
import http.server
import json
import threading
import time
from io import BytesIO, SEEK_END
from os import environ
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote

from .models import APIDisplayResponse, APISetupResponse, DashboardConfig, DeviceConfig, ScheduleEntry, RenderData
from .state import server_state
from .components import (
    render_dashboard_image,
    _create_info_image,
    eink_display,
    tile_components,
)
from .config import read_config, is_schedule_entry_visible, find_device, _coerce_time, _aligned_refresh_rate, _seconds_until_next_visible
from .firmware import resolve_firmware, _fw_differs, _repo_dir_name, FIRMWARE_CACHE_DIR
from .hass_client import HASS_URL, HASS_TOKEN

if TYPE_CHECKING:
    from logging import Logger

SERVER_NAME: str = environ.get("SERVER_NAME", "https://www.example.com")
```

- [ ] **Step 4: Initialize firmware locals and resolve firmware in `_handle_api_display`**

Replace:

```python
        out_filename: str = "device_not_found.png"
        image_url: str = f"{SERVER_NAME}/static/{out_filename}"
        refresh_rate: int = self.refresh_rate

        if device_id is None:
```

with:

```python
        out_filename: str = "device_not_found.png"
        image_url: str = f"{SERVER_NAME}/static/{out_filename}"
        refresh_rate: int = self.refresh_rate
        update_firmware: bool = False
        firmware_url: str | None = None

        if device_id is None:
```

Then replace:

```python
            device_config: DeviceConfig | None = find_device(devices, device_id)
            label: str = self._device_label(device_config, device_id)

            self.logger.debug("Request from device: %s", label)

            if device_config is None:
                self.logger.warning("Device %s not found in devices config.", label)
                image_url = f"{SERVER_NAME}/static/device_id/{device_id.replace(':', '-')}.png"
            else:
                out_filename = "no_dashboard_visible.png"
                image_url = f"{SERVER_NAME}/static/{out_filename}"
```

with:

```python
            device_config: DeviceConfig | None = find_device(devices, device_id)
            label: str = self._device_label(device_config, device_id)

            self.logger.debug("Request from device: %s", label)

            if device_config is None:
                self.logger.warning("Device %s not found in devices config.", label)
                image_url = f"{SERVER_NAME}/static/device_id/{device_id.replace(':', '-')}.png"
            else:
                fw_config = config.get('firmware')
                if fw_config:
                    current_fw: str | None = self.headers.get('FW-Version')
                    target_version: str = fw_config['version']
                    if current_fw is not None and _fw_differs(current_fw, target_version):
                        pattern: str = device_config.get('firmware_asset_pattern', fw_config['asset_pattern'])
                        cached_path: Path | None = resolve_firmware(
                            fw_config['repo'], target_version, pattern, FIRMWARE_CACHE_DIR, self.logger
                        )
                        if cached_path is not None:
                            update_firmware = True
                            firmware_url = (
                                f"{SERVER_NAME}/static/firmware/"
                                f"{quote(target_version, safe='')}/{quote(cached_path.name, safe='')}"
                            )

                out_filename = "no_dashboard_visible.png"
                image_url = f"{SERVER_NAME}/static/{out_filename}"
```

- [ ] **Step 5: Use the real firmware fields in the response dict**

Replace:

```python
        response: APIDisplayResponse = {
            "status": 0,
            "filename": f"{time.time()}-{out_filename}",
            "image_url": image_url,
            "image_url_timeout": 0,
            "reset_firmware": False,
            "update_firmware": False,
            "firmware_url": None,
            "refresh_rate": str(refresh_rate),
        }
```

with:

```python
        response: APIDisplayResponse = {
            "status": 0,
            "filename": f"{time.time()}-{out_filename}",
            "image_url": image_url,
            "image_url_timeout": 0,
            "reset_firmware": False,
            "update_firmware": update_firmware,
            "firmware_url": firmware_url,
            "refresh_rate": str(refresh_rate),
        }
```

- [ ] **Step 6: Add the `_handle_static_firmware` method**

Insert this new method immediately after `_handle_static_png` (which currently ends with `return False` right before the `def log_message` method):

```python
    def _handle_static_firmware(self) -> bool:
        """Handle GET /static/firmware/<version>/<filename> — serve a cached binary.

        Returns:
            True if a cached firmware file was found and served, False otherwise.
        """
        from urllib.parse import unquote

        path: str = unquote(self._parse_path())
        parts: list[str] = path[len('/static/firmware/'):].split('/')
        if len(parts) != 2 or '..' in parts[0] or '..' in parts[1]:
            return False
        version, filename = parts

        config = read_config(self.logger)
        fw_config = config.get('firmware')
        if not fw_config:
            return False

        file_path: Path = Path(FIRMWARE_CACHE_DIR) / _repo_dir_name(fw_config['repo']) / version / filename
        if not file_path.is_file():
            return False

        self.send_response(200)
        self.send_header('Content-type', 'application/octet-stream')
        self.send_header('Content-length', str(file_path.stat().st_size))
        self.end_headers()
        self.wfile.write(file_path.read_bytes())
        return True

```

- [ ] **Step 7: Register the route in `do_GET`**

Replace:

```python
            if path.startswith('/static/') and path.endswith('.png'):
                if self._handle_static_png():
                    return

            self.logger.warning("GET 404: %s (raw: %s)", path, self.path)
```

with:

```python
            if path.startswith('/static/firmware/'):
                if self._handle_static_firmware():
                    return

            if path.startswith('/static/') and path.endswith('.png'):
                if self._handle_static_png():
                    return

            self.logger.warning("GET 404: %s (raw: %s)", path, self.path)
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `uv run pytest tests/test_api.py -v`
Expected: PASS — all tests in `tests/test_api.py` pass, including the full pre-existing suite (this task must not regress any of the tests already listed in the earlier `tests/test_api.py` read, e.g. `test_api_display_basic`, `test_api_display_known_device_returns_dashboard_url`, etc.) plus the new `TestAPIFirmware` and `TestStaticFirmwareRoute` classes.

- [ ] **Step 9: Run the full test suite to check for regressions**

Run: `uv run pytest -v`
Expected: PASS — all tests across the whole suite (`test_api.py`, `test_config.py`, `test_components.py`, `test_font_asset.py`, `test_golden.py`, `test_hass_client.py`, `test_metrics.py`, `test_server_module.py`, `test_server.py`, `test_state.py`, `test_firmware.py`) pass.

- [ ] **Step 10: Commit**

```bash
git add src/trmnl_server/api.py tests/test_api.py
git commit -m "feat: serve firmware updates via /api/display and /static/firmware"
```

---

### Task 4: End-to-end test against the real GitHub API

**Files:**
- Create: `tests/test_firmware_e2e.py`

**Interfaces:**
- Consumes: `api.FIRMWARE_CACHE_DIR`, `api.SERVER_NAME` (module globals, monkeypatched for the test), `server.create_handler_class` (Task 3 / existing `server.py`).
- Produces: nothing consumed by later tasks — this is a leaf verification test.

This test intentionally hits the real network — no GitHub API mocking. Target repo: `cli/cli` (github.com/cli/cli), **not** an official TRMNL firmware repo. As of writing, the public TRMNL firmware repos (`usetrmnl/trmnl-firmware`, aka `usetrmnl/firmware`; `Seeed-Projects/Seeed_TRMNL_Eink_Project`; and other known forks) publish **zero** binary assets on their GitHub releases — verified via `curl https://api.github.com/repos/usetrmnl/trmnl-firmware/releases` returning `"assets": []` for every release. There is no real firmware repo to target. `cli/cli`'s releases always include a small `*_checksums.txt` asset (~2KB as of writing), which exercises the exact same GitHub releases API + asset-download code path a real firmware repo would use — fast, stable, and it uses `version: "latest"` so the test never goes stale as `cli/cli` cuts new releases.

- [ ] **Step 1: Write the test**

Create `tests/test_firmware_e2e.py`:

```python
"""End-to-end test for firmware update delivery — hits the real GitHub API.

No mocking: this test performs a real HTTP round trip through this server's
/api/display and /static/firmware routes, and independently re-fetches the
same GitHub release to verify the served bytes are byte-for-byte correct.

Target repo: cli/cli, not an official TRMNL firmware repo — as of writing,
none of the public TRMNL firmware repos publish binary release assets on
GitHub (their releases all have an empty "assets" list), so there is no real
firmware repo to test against. cli/cli's releases always include a small
"*_checksums.txt" asset, which exercises the identical release-lookup +
asset-download code path a real firmware repo would use. Uses `version:
"latest"` (not a pinned tag) so this test never goes stale.

Kept in its own file, separate from the rest of the (fully mocked) test
suite, since it is the only test here that depends on network access.
"""

import json
import os
import shutil
import socketserver
import tempfile
import threading
import unittest
import urllib.request
from logging import getLogger

from trmnl_server import api
from trmnl_server.server import create_handler_class


class TestFirmwareEndToEnd(unittest.TestCase):
    """Full HTTP round trip: /api/display -> firmware_url -> bytes match GitHub."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.cache_dir = os.path.join(self.tmp_dir, "cache")

        self.config_path = os.path.join(self.tmp_dir, "config.yaml")
        with open(self.config_path, "w") as f:
            f.write(
                "firmware:\n"
                "  repo: cli/cli\n"
                "  version: latest\n"
                '  asset_pattern: "*_checksums.txt"\n'
                "devices:\n"
                '  - id: "AA:BB:CC:DD:EE:FF"\n'
            )

        self._orig_cache_dir = api.FIRMWARE_CACHE_DIR
        self._orig_config_path = os.environ.get("CONFIG_PATH")
        api.FIRMWARE_CACHE_DIR = self.cache_dir
        os.environ["CONFIG_PATH"] = self.config_path

        Handler = create_handler_class(getLogger("test_firmware_e2e"))
        self.httpd = socketserver.TCPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self._orig_server_name = api.SERVER_NAME
        api.SERVER_NAME = f"http://127.0.0.1:{self.port}"

        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        api.FIRMWARE_CACHE_DIR = self._orig_cache_dir
        api.SERVER_NAME = self._orig_server_name
        if self._orig_config_path is None:
            os.environ.pop("CONFIG_PATH", None)
        else:
            os.environ["CONFIG_PATH"] = self._orig_config_path
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_display_then_firmware_download_matches_github(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/display",
            headers={"ID": "AA:BB:CC:DD:EE:FF", "FW-Version": "0.0.0"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            display = json.loads(resp.read().decode())

        self.assertTrue(display["update_firmware"])
        self.assertIsNotNone(display["firmware_url"])
        self.assertIn(f"http://127.0.0.1:{self.port}/static/firmware/", display["firmware_url"])

        with urllib.request.urlopen(display["firmware_url"], timeout=30) as resp:
            served_bytes = resp.read()

        # Independently resolve the same GitHub release to get ground truth.
        with urllib.request.urlopen(
            "https://api.github.com/repos/cli/cli/releases/latest", timeout=30
        ) as resp:
            release = json.loads(resp.read().decode())
        asset = next(a for a in release["assets"] if a["name"].endswith("_checksums.txt"))
        with urllib.request.urlopen(asset["browser_download_url"], timeout=30) as resp:
            expected_bytes = resp.read()

        self.assertEqual(served_bytes, expected_bytes)
        self.assertGreater(len(served_bytes), 0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test**

Run: `uv run pytest tests/test_firmware_e2e.py -v`
Expected: PASS — requires network access to `api.github.com` and `github.com`. If it fails with a connection error in a sandboxed/offline environment, that is an environment limitation (no network egress), not a code defect; re-run in an environment with network access before treating a failure here as a real bug.

- [ ] **Step 3: Commit**

```bash
git add tests/test_firmware_e2e.py
git commit -m "test: add real-network e2e test for firmware update delivery"
```

---

### Task 5: Documentation

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: the final, working behavior from Tasks 1–4 (this task only documents; write it last so the docs describe what was actually built).

- [ ] **Step 1: Add the `FIRMWARE_CACHE_DIR` env var to the Environment Variables table**

In `README.md`, replace:

```markdown
| `CONFIG_PATH` | No | Path to the config file (default: `config.yaml`) |
| `PORT` | No | Port to listen on (default: `8000`) |
| `DEBUG` | No | Set to any non-empty value to enable debug logging |
```

with:

```markdown
| `CONFIG_PATH` | No | Path to the config file (default: `config.yaml`) |
| `PORT` | No | Port to listen on (default: `8000`) |
| `DEBUG` | No | Set to any non-empty value to enable debug logging |
| `FIRMWARE_CACHE_DIR` | No | Directory used to cache downloaded firmware binaries (default: `firmware_cache`). Only used if `firmware:` is set in `config.yaml`. |
```

- [ ] **Step 2: Document the `firmware:` config block**

In `README.md`, immediately after the `#### \`dashboards\`` section's closing code block and before the `#### Component Types` heading, insert:

````markdown
#### `firmware` (optional)

Enables self-hosted firmware update delivery. When set, `/api/display` compares each device's `FW-Version` request header against `version`; on a mismatch, the server fetches the matching release asset from the configured GitHub repo (caching it to disk under `FIRMWARE_CACHE_DIR` on first use) and tells the device to update.

```yaml
firmware:
  repo: usetrmnl/firmware      # GitHub "owner/repo" to pull releases from
  version: v1.6.0              # Exact release tag, or "latest"
  asset_pattern: "*.bin"       # fnmatch glob used to pick the release asset by filename
```

A release can publish multiple board-variant binaries; `asset_pattern` selects which one to serve. Since board variant is fixed per physical device, an individual device can override the default pattern:

```yaml
devices:
  - id: "AA:BB:CC:DD:EE:FF"
    firmware_asset_pattern: "*seeed_xiao_esp32c3*.bin"
```

If `firmware:` is omitted, `/api/display` always returns `update_firmware: false` and `firmware_url: null` (unchanged from previous versions of this server). Any resolution failure (repo/tag not found, no asset matches the pattern, GitHub unreachable) degrades the same way and logs a warning — it never affects dashboard image serving.
````

- [ ] **Step 3: Add the `FW-Version` header to the device headers table**

In `README.md`, replace:

```markdown
| Header | Description |
|--------|-------------|
| `ID` | Device MAC address (primary identifier) |
| `Battery-Voltage` | Optional battery voltage, rendered on the dashboard image |
| `X-Forwarded-For` | Used as device ID if `ID` header is absent (proxy environments) |
```

with:

```markdown
| Header | Description |
|--------|-------------|
| `ID` | Device MAC address (primary identifier) |
| `Battery-Voltage` | Optional battery voltage, rendered on the dashboard image |
| `FW-Version` | Device's current firmware version; compared against `firmware.version` in `config.yaml` when present |
| `X-Forwarded-For` | Used as device ID if `ID` header is absent (proxy environments) |
```

- [ ] **Step 4: Update the `/api/display` example response**

In `README.md`, replace:

```json
{
    "filename": "1678886400.0-weekday_morning.png",
    "image_url": "https://trmnl.example.com/static/weekday_morning.png",
    "image_url_timeout": 0,
    "reset_firmware": false,
    "update_firmware": false,
    "refresh_rate": 600
}
```

with:

```json
{
    "filename": "1678886400.0-weekday_morning.png",
    "image_url": "https://trmnl.example.com/static/weekday_morning.png",
    "image_url_timeout": 0,
    "reset_firmware": false,
    "update_firmware": false,
    "firmware_url": null,
    "refresh_rate": 600
}
```

Directly below that code block, add: `"update_firmware"` is `true` and `"firmware_url"` is set when a \`firmware:\` block is configured and the device's \`FW-Version\` header doesn't match the target version — see [`firmware` (optional)](#firmware-optional) above.

- [ ] **Step 5: Document the new static route**

In `README.md`, replace:

```markdown
### `GET /static/<dashboard_name>.png`

Renders and serves the PNG image for the named dashboard. The device must have that dashboard in its schedule; unrecognised devices or out-of-schedule requests receive a 404.
```

with:

```markdown
### `GET /static/<dashboard_name>.png`

Renders and serves the PNG image for the named dashboard. The device must have that dashboard in its schedule; unrecognised devices or out-of-schedule requests receive a 404.

### `GET /static/firmware/<version>/<filename>`

Serves a cached firmware binary. Only reachable when `firmware:` is configured; `version`/`filename` come directly from the `firmware_url` returned by `/api/display`. Returns a 404 if the file isn't in the cache (e.g. `FIRMWARE_CACHE_DIR` was cleared).
```

- [ ] **Step 6: Commit**

```bash
git add README.md
git commit -m "docs: document self-hosted firmware update delivery"
```
