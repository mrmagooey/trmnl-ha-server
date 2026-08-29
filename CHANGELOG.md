# Changelog

## [Unreleased]

### Added
- New `url` component type fetches a value from an arbitrary http(s) URL and renders it as text, with optional `json_path` (a basic jq-style path, e.g. `.data.items[0].name`) and `regex` extraction — `json_path` runs first when set, then `regex` against its result, falling back to the raw response body when neither is set. Fetches run on a background thread pool and are cached (`cache_ttl`, default 300 seconds), so rendering never blocks on the network: a panel shows "No data" until its first fetch completes, and if a source later goes down the last successfully fetched value keeps rendering rather than blanking. Request headers aren't configurable, so an API key belongs in the URL's query string; URLs are redacted to scheme/host/path in log output so keys are never written to the persisted log file.

### Fixed
- Requesting `/static/<dashboard>.png` without an `ID` header returned HTTP 500 instead of an image. The per-device rotation lookup read `device_config` unconditionally, but that variable was only assigned for requests that carried a device ID, so an ID-less request raised `UnboundLocalError`. Such a request now renders the dashboard with no device-specific rotation applied.
- A long panel value with no spaces in it — a JSON object, a hash, an id — was clipped at both tile edges instead of being truncated. Word wrapping splits on spaces, so such a value stayed on one over-wide line and was centred at a negative offset, cutting off its start as well as its end. Any line that still does not fit after wrapping is now ellipsized, so the value reads from the beginning and ends in `…`. Values that already fit render identically.
- Entity-list rows and calendar events with unbreakable text — a JSON object, a hash, an id — ran off the right edge of their panel. Neither renderer wraps its rows, so once the font shrink loop reached its floor the text was drawn past the tile boundary and clipped. Such rows are now truncated with a trailing ellipsis, matching how todo items already behaved.

## [1.7.1] - 2026-08-28

### Fixed
- Rendering is now reproducible across machines. Pillow selects its text-shaping engine at import time depending on whether the host happens to have `libfribidi` installed, and the two engines produce glyph widths differing by a fraction of a percent — enough to change the chosen title font size and every rendered pixel. The basic layout engine is now forced explicitly. The shipped Docker image already used it, so add-on rendering is unchanged.
- CI could not install dependencies (and so never ran the tests or published an image) since 1.5.0: `uv` was matching the runner's preinstalled Python 3.12.3 against this project's `>=3.12.5` requirement instead of fetching a compliant interpreter.

## [1.7.0] - 2026-08-28

### Added
- Dashboard grid panels sharing a row now render their titles at one shared font size instead of each shrinking independently, so neighbouring panels no longer differ visibly. A row whose size would be dragged down by one long title instead wraps that title onto two lines, keeping the larger font. Titles that still do not fit are ellipsis-truncated rather than clipped.

### Fixed
- Entity values on short tiles (roughly under 183px tall) were clipped top and/or bottom — `21.5` could render as `21 5` with its decimal point cut off. The value is now sized against the available height, not just the available width, and kept within the tile.

## [1.6.0] - 2026-07-03

### Added
- history_graph: optional `zero_baseline` flag draws an in-graph zero reference line for values that span positive and negative.
- Added /api/metrics endpoint reporting dashboards served (last 7 days, by device id) and per-device daily battery state.
- Optional self-hosted firmware update delivery: configure a `firmware` block (GitHub repo, version, asset pattern) in `config.yaml`, with an optional per-device `firmware_asset_pattern` override, and the server resolves, caches, and serves the matching release binary via `/api/display`'s `update_firmware`/`firmware_url` fields whenever a device's `FW-Version` header doesn't match the target.

## [1.5.0] - 2026-06-14

### Added
- `entity` and `entities` components support an optional `attribute` field to display a specific Home Assistant entity attribute (e.g. a `climate.*` entity's `current_temperature`) instead of the entity state. Omit it to show the state, as before; for `entities` it is set per row. A missing attribute renders blank.

## [1.4.0] - 2026-06-09

### Added
- When no dashboard is scheduled for the current time, the device now sleeps until the next scheduled entry's window opens instead of polling on a fixed timer, so scheduled dashboards appear on time. Falls back to a 600-second refresh if nothing is upcoming within about a week.

### Fixed
- Timed dashboard displays no longer drift forward by the per-refresh processing delay. The `/api/display` refresh rate is aligned to an absolute cadence grid (anchored at the schedule entry's start time, with correct overnight handling) rather than a fixed relative interval.

## [1.3.0] - 2026-06-08

### Added
- `todo_list` components support multiple columns via an optional `columns` field (default 1). When incomplete items overflow the card, the list paginates — cycling to the next page on each refresh — and shows the incomplete-item count plus a page indicator (e.g. `2/3`).

## [1.2.0] - 2026-06-07

### Added
- Per-device display rotation via a `rotate` field on each device, allowing a different orientation per TRMNL device.
- Configurable history-graph time window via a per-component `hours` field (default 24). The graph's x-axis now always ends at the current time, and when an entity stops reporting its last value is held forward as a dotted line.

### Changed
- Restructured the codebase into a `src/trmnl_server` package; the server now runs as `python -m trmnl_server.server`. Sample `config.yaml` and `deployment.yaml` moved to `examples/`. No change to add-on behaviour or configuration.

## [1.1.0] - 2026-04-13

### Added
- Support 180-degree display rotation via `rotate: 180` dashboard config.

### Fixed
- URL-encode image paths and strip trailing slashes from routes.
- Route BaseHTTPRequestHandler logs through the application logger.
- Normalise request path and log 404s at WARNING level.
- Align API responses with TRMNL firmware spec.
- Handle POST /api/setup for TRMNL firmware compatibility.
- Strip query string from path before routing GET requests.

## [1.0.0] - 2026-04-06

Initial release.
