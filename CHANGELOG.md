# Changelog

## [Unreleased]

### Changed
- Calendar panels no longer repeat the weekday on every row. Each event row used to start with its full day name (`Wednesday 10:00-12:00: ...`), which said the same thing on every row in the common case (a panel showing one day) and crowded out the summary even when it didn't — on a typical tile roughly two-thirds of a row's width went to that prefix. Events are now grouped by day, and each group's weekday is drawn once as a three-letter label (`Wed`) rotated to read bottom-to-top in a narrow strip down the left edge, with a rule separating it from the rows. When a tile is too narrow or too short for that strip to read comfortably, or when an event's start time can't be parsed, the panel falls back to putting the day back on the front of every row instead (`Wed 10:00-12:00  ...`) rather than mixing the two styles. Either way, the freed-up width goes to the summary, which now truncates later. Separately, event text no longer grows to fill a panel's width without regard for its height — a calendar with only short summaries used to inflate to a size that then pushed later events off the bottom of the panel, discarding them silently. Panel height is now part of the same sizing decision, and if events still don't all fit, the panel says so with a trailing "+N more" line rather than just cutting them off.

## [1.10.0] - 2026-09-09

### Changed
- Calendar event rows are no longer shrunk below 20pt to make a long summary fit. The shrink-to-fit ladder previously bottomed out at 16pt, so a single over-long event — a summary carrying a weekday, a time range and a long title — dragged the whole panel down to a size that is hard to read on an e-ink panel at arm's length. The floor for a calendar is now 20pt and anything that still does not fit is truncated with an ellipsis instead: a long summary costs its own tail rather than the panel's legibility. Because panels sharing a layout row render at one size, a calendar raises that floor for its row-mates too, so an entity list or todo list beside a calendar may now truncate rows it previously rendered in full. An empty calendar draws a placeholder rather than rows and so does not affect its neighbours, and a row with no calendar in it still reaches 16pt as before.

## [1.9.0] - 2026-09-06

### Added
- New `gap_style` option on `history_graph` panels chooses how an outage is drawn: `hold` (the default — a dashed line holding the last known value flat across the gap), `break` (nothing drawn; the line stops and restarts), or `step` (the dashed hold plus a dashed vertical riser joining it to the recovered value, so the series reads as one connected step). Under `hold` the jump from the held value to the recovered one is left undrawn, which makes the line read as two detached pieces; `step` exists for anyone who would rather keep it visually connected, and `break` for anyone who would rather the graph draw nothing it did not measure. An entity that stops reporting and has not returned still gets its dotted tail to the right edge under every style.

### Changed
- Panel body text — entity-list rows, calendar events and todo items — now renders at one size within each panel, and at one size across all the panels sharing a layout row, matching how panel titles were already harmonised. Every row previously ran its own shrink-to-fit loop, so a single entity list could show four rows at 28, 15, 28 and 12pt with the gap between them tracking each row's own ink height. Sizes are now quantised to a ladder and a group takes the largest rung that fits all of its rows. Two consequences worth knowing: the size floor rises from roughly 10pt to 16pt, so an over-long row is truncated rather than shrunk to illegibility — entity rows truncate the name and keep the state value, which is the half worth reading — and a todo list is sized against every incomplete item rather than just the page on screen, so its text no longer changes size as it cycles pages.

### Fixed
- A `history_graph` drew a smooth line straight through an outage. Readings Home Assistant reported as `unavailable` or `unknown` were silently discarded, so the remaining points were joined into one continuous polyline — asserting a trend across the gap that was never measured. Those states are now preserved as gap markers and the span is drawn dashed instead of interpolated.
- A large entity value could be drawn past the bottom edge of its tile and clipped. The value's vertical centring used a fixed offset calibrated for the single-line title layout, where the title overlaps the value's region rather than sitting in its own band; once a title wrapped to two lines the space left over still admitted a very large font, and the offset — which does not scale with font size — under-corrected. The value's ink box is now centred in the space actually available to it and clamped to the tile, which also fixes a pre-existing single-line case that had gone unnoticed.

## [1.8.1] - 2026-08-29

### Fixed
- The "No dashboard is scheduled for display." placeholder (and the device-ID image) ignored rotation, so a rotated device showed it sideways or upside down. Only dashboard renders passed through the rotation step; the plain info images were served straight out of the renderer. They now use the same rotation as the dashboards would: the device's `rotate`, or — when that is unset — the rotation its scheduled dashboards agree on, so a device configured only with `portrait: true` on its dashboards is covered too. The placeholder's image URL now carries the device ID (`/static/<id>/no_dashboard_visible.png`) so the rotation can be resolved without relying on the `ID` header.

## [1.8.0] - 2026-08-28

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
