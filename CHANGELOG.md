# Changelog

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
