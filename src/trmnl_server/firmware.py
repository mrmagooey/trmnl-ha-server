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
