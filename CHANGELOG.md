# Changelog

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
