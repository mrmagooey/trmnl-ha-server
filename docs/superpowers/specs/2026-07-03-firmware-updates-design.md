# Self-hosted firmware update delivery — design

## Problem

TRMNL devices poll `/api/display` and the response can instruct a device to
download and flash new firmware via three fields: `update_firmware` (bool),
`firmware_url` (string|null), `reset_firmware` (bool, unrelated to updates —
used for ownership transfer/reset). Today this server always returns
`update_firmware=false` / `firmware_url=null` — firmware push isn't wired up.

This design adds a mechanism where the server itself resolves and serves the
firmware binary, fetched and cached from a configured GitHub releases repo,
so a fleet of devices can be kept on a pinned firmware version without any
external service.

## Architecture

Three additions, no changes to existing dashboard rendering:

1. **`firmware.py`** (new module) — resolves a target GitHub release to a
   cached local `.bin` file on disk. Pure function, no HTTP-handler
   concerns.
2. **`api.py` changes** — `_handle_api_display` reads the device's
   `FW-Version` request header, compares it against the configured target
   version, and if they differ, asks `firmware.py` to resolve the cached
   binary. A new route, `GET /static/firmware/<version>/<filename>`, serves
   the cached binary bytes directly from disk (unlike PNGs, firmware isn't
   rendered — it's a real file read from the cache directory).
3. **Config additions** — a top-level `firmware:` block (repo, target
   version, default asset pattern) plus an optional per-device
   `firmware_asset_pattern` override, following the existing YAML-config
   style.

## Config schema

```yaml
# Top-level, alongside `devices:` and `dashboards:`
firmware:
  repo: usetrmnl/firmware        # GitHub "owner/repo"
  version: v1.6.0                # exact release tag, or "latest"
  asset_pattern: "*.bin"         # default glob for picking the release asset

devices:
  - id: "AA:BB:CC:DD:EE:FF"
    name: "Living Room"
    firmware_asset_pattern: "*seeed_xiao_esp32c3*.bin"  # optional per-device override
    ...
```

- `firmware:` block is entirely optional. If absent, behavior is unchanged
  (`update_firmware` always `false`, `firmware_url` always `null`).
- `version: latest` resolves via GitHub's `/releases/latest`; any other
  string is treated as an exact tag via `/releases/tags/{version}`.
- `asset_pattern` is a glob (`fnmatch`) matched against release asset
  filenames — needed because one release can publish multiple board-variant
  binaries. A per-device `firmware_asset_pattern` overrides the global
  default (board variant is fixed per physical device).
- `models.py` additions: `DeviceConfig` gains an optional
  `firmware_asset_pattern: str` key. A new `FirmwareConfig` TypedDict
  (`repo: str`, `version: str`, `asset_pattern: str`) is added and `Config`
  gains an optional `firmware: FirmwareConfig` key.

## Fetch & cache module (`firmware.py`)

```python
def resolve_firmware(
    repo: str, version: str, asset_pattern: str,
    cache_dir: Path, logger: Logger,
) -> Path | None:
    """Return a local path to the matching release asset, downloading it if needed."""
```

- **Cache layout:** `<cache_dir>/<repo with "/" -> "_">/<version>/<asset_filename>`.
  If that file already exists on disk, return it immediately — no network
  call.
- **Cache miss:** call the GitHub REST API anonymously (no token; the
  anonymous 60/hr rate limit is ample since this only fires once per version
  change) — `GET /repos/{repo}/releases/latest` or
  `GET /repos/{repo}/releases/tags/{version}` — find the first asset whose
  `name` matches `asset_pattern` via `fnmatch.fnmatch`, download its
  `browser_download_url` to the cache path (write to a temp file then
  rename, to avoid serving a partially-written file to a concurrent
  request), and return the path.
- **Concurrency:** a module-level `threading.Lock` (same pattern as
  `_dashboard_lock` in `api.py`) serializes resolution so concurrent devices
  polling at once don't trigger duplicate downloads for the same
  `(repo, version, pattern)`.
- **Negative caching:** on failure (network error, tag not found, no asset
  matches the pattern), remember the failure for that
  `(repo, version, pattern)` key with a 5-minute cooldown. Within the
  cooldown, `resolve_firmware` returns `None` immediately without hitting
  GitHub again, and only the first failure in a cooldown window is logged
  (avoids log/API spam from a misconfigured repo or pattern being hit by
  every device's poll cycle).
- **Cache directory:** `FIRMWARE_CACHE_DIR` env var, default
  `"firmware_cache"` (relative path, matching the existing `CONFIG_PATH`
  env var's convention of defaulting to `"config.yaml"`).
- **`"latest"` caching caveat:** because the cache key includes the literal
  `version` string, `version: "latest"` is resolved once and then served
  from cache indefinitely — it does not re-check GitHub for newer releases
  on subsequent requests. This is a direct consequence of the "download
  once, reuse until target version changes" caching design; clearing
  `FIRMWARE_CACHE_DIR` is the way to force a re-resolution.

## API integration (`api.py`)

In `_handle_api_display`, after the existing dashboard-selection logic, and
only when a `device_config` was found:

```python
fw_config = config.get('firmware')
if fw_config and device_config is not None:
    current_fw = self.headers.get('FW-Version')
    target_version = fw_config['version']
    if current_fw is not None and _fw_differs(current_fw, target_version):
        pattern = device_config.get('firmware_asset_pattern', fw_config['asset_pattern'])
        cached = resolve_firmware(fw_config['repo'], target_version, pattern, cache_dir, self.logger)
        if cached is not None:
            update_firmware = True
            firmware_url = f"{SERVER_NAME}/static/firmware/{quote(target_version)}/{quote(cached.name)}"
```

- `_fw_differs(a, b)` strips a leading `v`/`V` from both sides before string
  comparison — avoids a spurious "update needed" result purely from
  `1.6.0` vs `v1.6.0` tag-format differences.
- If the `FW-Version` header is absent (older firmware, or a manual test
  request), firmware fields stay `false`/`null` — same as today.
- Any resolution failure degrades to `false`/`null` plus a logged warning —
  it never breaks the dashboard-serving response. Firmware fields are
  additive; a firmware misconfiguration must not take down the actual
  display service.

### New static route

`GET /static/firmware/<version>/<filename>`:

- Validates that `version` and `filename` contain no `..` or `/`
  path-traversal characters (reject with 404 if so).
- Looks up `<cache_dir>/<repo>/<version>/<filename>` directly — the route
  only carries `version`/`filename`, but `repo` comes from the currently
  configured `firmware.repo` (there's exactly one repo configured at a
  time), so the handler builds the path without any lookup or scan.
- Serves the file with `Content-type: application/octet-stream` and a
  `Content-length` header (same pattern as `_send_png`).
- 404s if the file isn't present in the cache (e.g. cache was cleared, or
  the URL is stale from a previous config).

## Error handling summary

| Failure | Behavior |
|---|---|
| No `firmware:` config | Feature inactive, existing `false`/`null` behavior |
| No `FW-Version` header from device | Feature inactive for that request |
| GitHub API unreachable / rate-limited | `resolve_firmware` returns `None`, logs once per 5 min cooldown, dashboard response unaffected |
| Configured tag doesn't exist | Same as above |
| No release asset matches `asset_pattern` | Same as above |
| Requested `/static/firmware/...` file not in cache | 404 |
| Path-traversal attempt in firmware static route | 404 |

## Testing plan

- **Unit** (`tests/test_firmware.py`): `resolve_firmware` with the GitHub
  HTTP calls stubbed — cache hit returns immediately with no network call;
  cache miss fetches release JSON, matches `asset_pattern` via `fnmatch`,
  downloads, and writes to cache; failure paths (404 tag, no matching
  asset, network error) return `None` and populate the cooldown. Also unit
  tests for `_fw_differs` (`v1.6.0` vs `1.6.0` equal, matching versions
  equal, differing versions not equal).
- **Integration** (`tests/test_api.py` additions): `_handle_api_display`
  with `firmware.py`'s network layer monkeypatched, verifying the
  response's `update_firmware`/`firmware_url` fields flip correctly based
  on `FW-Version` header vs. configured target version, that dashboard
  image serving is unaffected when firmware resolution fails, and that
  per-device `firmware_asset_pattern` overrides the global default. Plus
  the new `/static/firmware/<version>/<filename>` route: serves cached
  bytes with the correct content-type, 404s when absent, rejects
  path-traversal attempts.
- **End-to-end** (`tests/test_firmware_e2e.py`, new file, isolated from the
  rest of the suite since it's the first test in this repo to hit real
  network): a device polls `/api/display` with a stale `FW-Version` header
  against a `firmware:` block pointed at the real `usetrmnl/firmware`
  GitHub repo and a real pinned release tag, then fetches the returned
  `firmware_url` from the running server and confirms the downloaded bytes
  match the real GitHub release asset. Accepted tradeoff: this test depends
  on GitHub being reachable and that repo's release/asset shape remaining
  stable — kept in its own file so it can be excluded from a fast/offline
  test run if that ever becomes necessary.

## Out of scope

- `reset_firmware` — unrelated to update delivery (device ownership
  transfer/factory reset), left as `false` always.
- Per-device pinned firmware versions (staged/canary rollout) — only a
  single global target version is supported; add per-device version
  targeting later if a real need arises.
- Authenticated GitHub API access (private repos, higher rate limits) — not
  needed at anonymous rate limits given the caching/cooldown design.
