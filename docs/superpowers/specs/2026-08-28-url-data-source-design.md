# URL data source — design

## Problem

Every panel type today is fed by Home Assistant. Data that does not live in HA —
a public JSON API, a status page, a plain-text endpoint — cannot reach a
dashboard at all. This adds a first non-HA data source: a component that fetches
a URL and renders text from the response.

## Requirements (from the request)

- A config item that takes a URL and renders the text returned from it.
- Accept JSON and pull text out with basic jq-style path parsing.
- Accept unstructured data and pull text out with a regex.
- Cache: only retrieve new data once the cache has expired.
- Must not block dashboard rendering if retrieval takes more than 60 seconds.

## Config

```yaml
- friendly_name: "Bitcoin"
  type: url
  url: "https://api.example.com/price.json"
  json_path: ".data.amount"   # optional
  regex: "([0-9.]+)"          # optional
  cache_ttl: 600              # optional, seconds, default 300
  timeout: 10                 # optional, seconds, default 10, capped at 60
```

`large_display` works as it does for any other component.

## Architecture

New module `src/trmnl_server/url_source.py` owns fetching, caching and
extraction. `render_dashboard_image` gains one branch that calls into it; the
existing entity renderer draws the result.

### Fetch and cache

- Module-level cache `dict[str, tuple[float, str | None]]` mapping URL to
  `(attempted_at, body)`, guarded by a `threading.Lock`.
- `attempted_at` is written on **every** attempt, success or failure; the body is
  overwritten only on success. A permanently broken URL is therefore retried at
  most once per `cache_ttl` instead of on every render.
- The cache is keyed by URL and stores the **raw response body**. Two components
  reading different fields of the same URL share one fetch. Each component judges
  freshness against **its own** `cache_ttl`, so the strictest TTL drives refreshes
  and the laxer one rides along.
- Fetches run on a module-level `ThreadPoolExecutor(max_workers=4)`. In-flight
  futures are held in `dict[str, Future]` keyed by URL so concurrent renders
  cannot pile up duplicate fetches for one URL.

### Never blocking (the 60s requirement)

The server is a single-threaded `socketserver.TCPServer`; `render_dashboard_image`
runs on the one and only request thread. Any bounded wait there stalls **every**
device and endpoint, and a permanently unreachable URL would pay that stall on
every render forever. So the render thread never waits at all:

| Cache state | Behaviour |
|---|---|
| Fresh | Return cached body immediately. |
| Stale | Return the stale body immediately, submit a background refresh. |
| Cold | Return `None` immediately (panel shows "No data"), submit a background fetch. |

This is strictly stronger than the 60s ceiling asked for. `timeout` is the socket
timeout for the **background worker only** — it stops a worker hanging on a dead
socket and never bounds the render thread.

The server is deliberately **not** made threaded: with nothing blocking on the
render path it buys this feature nothing, and changing the concurrency model
touches shared `ServerState` and image file writes. (For reference, the existing
HA fetches call `urlopen` with no timeout at all on that same thread.)

### Startup prefetch

`server.main()` calls `url_source.prefetch(config, logger)` before
`serve_forever()`, submitting a background fetch for every `url` component in the
config. Without it, every addon restart blanks every URL panel until the next
device refresh.

**Known limitation:** prefetch runs once at startup. A `url` component added to a
running server's config gets no prefetch, so its panel renders "No data" until the
first render-triggered background fetch completes — bounded by the device's
`refresh_rate` (typically 600s). Documented in the README; the panel self-heals on
the following cycle.

### Extraction

Applied in order to the response body:

1. `json_path` if set — a mini jq-style parser over `json.loads`: `.a.b[0].c`,
   dot-separated keys plus integer indices, leading dot optional. A missing key,
   an out-of-range index, or traversing into a non-container yields `None`.
2. `regex` if set — `re.search` against the current value. Returns group 1 if the
   pattern defines groups, else group 0. No match yields `None`.
3. Neither set — the raw body, stripped.

Non-string values are stringified as `value if isinstance(value, str) else
json.dumps(value)`, so a path landing on a list or dict feeds regex real JSON text
rather than a Python repr, and ints/floats/booleans render as `42`, `42.5`, `true`.
A JSON `null` yields `None` (panel shows "No data"), not the literal text `null`.

The extracted text is rendered **verbatim** — unlike the `entity` type it is not
cast to a number, because the request is to render the text returned.

### Failure behaviour

Consistent with the rest of the codebase: log, return `None`, never raise.

- Fetch failure → log ERROR, keep serving the last successfully fetched body
  indefinitely. A stale value beats a blank panel on an e-ink display.
- Extraction failure against a healthy body (upstream schema changed) → log
  WARNING, panel renders "No data". The cache holds bodies, not extracted values,
  so there is no "last good extraction" to fall back to — and an upstream schema
  change is something the operator needs to see rather than have papered over.

### Safety

- Only `http` and `https` URLs are fetched; anything else is refused with a
  warning. Blocks `file://` reads of local files.
- At most 1 MiB is read from a response, so a runaway endpoint cannot OOM the
  server.
- **URLs are redacted in every log message** — scheme, netloc and path only, query
  string and fragment stripped. The documented v1 pattern for authenticated
  sources is an API key in the query string, and logs go to a persisted
  `RotatingFileHandler` under `/logs`, so logging URLs verbatim would write
  secrets to disk. This applies to `config.py`'s new `url` validator too, which
  must **not** echo the value with `%r` the way the surrounding validators do.
- Auth headers are not configurable in v1. API keys go in the query string;
  documented in the README.

## Changes to existing files

- `models.py` — `ComponentConfig` gains `url`, `json_path`, `regex`, `cache_ttl`,
  `timeout`; its `type` Literal gains `"url"`.
- `config.py` — `"url"` added to `VALID_COMPONENT_TYPES`; `_validate_config` warns
  (never raises) on a missing or non-http(s) `url`, a `regex` that fails to
  compile, and a non-positive-integer `cache_ttl` / `timeout`. No warning echoes
  the URL value.
- `components.py` — an `elif component_type == 'url':` branch in
  `render_dashboard_image` calling `fetch_url_value`; in `_render_component`,
  `elif component_type == 'entity':` becomes
  `elif component_type in ('entity', 'url'):`.
- `server.py` — `main()` calls `url_source.prefetch(...)` before `serve_forever()`.
- Docs — README component docs (including the API-key and prefetch caveats),
  `examples/config.yaml`, CHANGELOG.

## Module API

```python
DEFAULT_CACHE_TTL = 300
DEFAULT_TIMEOUT   = 10
MAX_TIMEOUT       = 60
MAX_BYTES         = 1_048_576

def _redact(url: str) -> str: ...
def _fetch(url: str, timeout: int, logger: Logger) -> None: ...          # worker
def get_url_text(url, *, cache_ttl, timeout, logger) -> str | None: ...  # never waits
def _json_path(obj: object, path: str) -> object | None: ...
def extract_value(body, *, json_path, regex, logger) -> str | None: ...
def fetch_url_value(component: ComponentConfig, logger: Logger) -> str | None: ...
def prefetch(config: Config, logger: Logger) -> None: ...
def reset_cache() -> None: ...                                          # tests
def _wait_for_pending(timeout: float = 10.0) -> bool: ...               # tests
```

## Testing

**Unit** — `_json_path` (nested keys, array indices, missing key, non-container
traversal, malformed path); `extract_value` (raw / path only / regex only / both /
no match / invalid JSON / JSON null / non-string stringification); cache freshness
with an injected clock; `attempted_at` updated on failure so a dead URL is not
refetched within its TTL; in-flight dedup; scheme guard; 1 MiB cap; the 60s
timeout cap; `_redact` strips query strings.

**Integration** — `render_dashboard_image` with a fake `urlopen`: the extracted
value renders; a cold cache returns immediately while a deliberately slow fake
fetch is still running (upper-bound assertion only) and shows "No data"; a stale
cache renders the stale value and schedules a refresh; a golden image for a `url`
panel; `_validate_config` warnings never contain the query string.

**End-to-end** — a real `http.server` on localhost serving a JSON body, driven
through the full `/api/display` → PNG flow (following `tests/test_firmware_e2e.py`).
Synchronised via `_wait_for_pending()`, not sleeps: request 1 (cold, "No data",
schedules fetch) → `_wait_for_pending()` → request 2 (renders the value).
