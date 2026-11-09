# Dithered `image` component — design

**Request (verbatim):** "What's the best way to display a greyscale image from home assistant?"
The assistant recommended a new image component (fetch from the HA API via camera_proxy /
image_proxy, resize to the tile, greyscale, optional contrast boost, dither, paste after the
LANCZOS downscale so the dots survive the 1-bit threshold, cache like the url component) that
"works on any TRMNL and leaves your existing dashboards untouched". User: "Yes".

**Constraint:** existing dashboards must render exactly as before.

Designed autonomously (auto-develop); the decision log below was approved by an independent
coherence review, whose conditions are folded in.

## Behaviour

A new component type renders a Home Assistant `camera.*` or `image.*` entity as a dithered
1-bit picture beneath the usual panel title:

```yaml
- type: image
  entity_name: camera.front_door
  friendly_name: Front door
  timeout: 5          # optional, seconds, default 5, capped at 15
  hide_title: false   # optional, as for every component
  large_display: true # optional, as for every component
```

The picture is scaled to fit the panel body with its aspect ratio preserved (letterboxed on
white, never cropped), auto-contrasted, then Floyd–Steinberg dithered. If the fetch fails the
last good picture for that entity is shown; if there has never been one the panel shows the
standard "No data for <name>" placeholder.

## Decision log

| # | Question | Options | Chosen | Why | Confidence |
|---|---|---|---|---|---|
| 1 | Config shape | new `image` type w/ `entity_name`; `url` field; `entity_picture` attribute | `type: image`, `entity_name: camera.x` / `image.x` | Mirrors every other HA component | high |
| 2 | HA endpoint | `/api/camera_proxy/<id>` / `/api/image_proxy/<id>` by domain; follow `entity_picture` | Proxy by domain with the existing Bearer token; entity id URL-quoted; other domains → config warning and "No data" | One request, no rotating access token | high |
| 3 | Fetch timing | background cache like `url`; synchronous fetch with timeout + last-good fallback | Synchronous fetch during the render, `timeout` default **5s**, capped at **15s**; last good image per entity kept in memory as fallback | **Departs from "cache like the url component"**: a background cache always serves the snapshot from the *previous* refresh (≈10 min stale for a camera) and blanks the first render. Other HA fetches already run synchronously in the render. The server is a single-threaded `socketserver.TCPServer`, so the timeout is kept short. | medium |
| 4 | Dither algorithm | Pillow Floyd–Steinberg; hand-written Atkinson; selectable | Pillow FS via `convert('1')` | Built in and fast; Atkinson in pure Python is slow; a selector is YAGNI | high |
| 5 | Contrast | none; always autocontrast; configurable | Always `ImageOps.autocontrast(cutoff=1)` before dithering (documented) | Flat camera frames otherwise dither to grey mush | medium |
| 6 | Fit | contain; cover; option | Contain, centred on white (documented; `fit` can be added later) | Never crops content | medium |
| 7 | Where dithering happens | dither then 2× + LANCZOS; title at 2× → LANCZOS → paste dithered at final px | The latter | Dots stay pure 0/255, so `eink_display`'s threshold and lossless rotation preserve them | high |
| 8 | Title | standard title + `hide_title`; none | Standard title, joins row title harmonisation; `hide_title` honoured | Consistency | high |
| 9 | Safety | none; caps + guards | Read ≤ 10 MB; reject images over 16 MP by `im.size` before `load()`; `DecompressionBombWarning` treated as error; JPEG `draft()`; HTTPError (incl. 401/404, logged with status and entity, never the token) / URLError / decode errors → log + fallback | Untrusted bytes must never crash a render | high |
| 10 | Existing behaviour | — | `eink_display`, other components and all existing goldens unchanged | User constraint | high |

## Design

### `hass_client.py`

- `IMAGE_DOMAIN_ENDPOINTS = {"camera": "camera_proxy", "image": "image_proxy"}`,
  `IMAGE_DEFAULT_TIMEOUT = 5`, `IMAGE_MAX_TIMEOUT = 15`, `IMAGE_MAX_BYTES = 10_485_760`,
  `IMAGE_MAX_PIXELS = 16_000_000`.
- `fetch_entity_image(entity_name: str, logger, *, timeout: int = IMAGE_DEFAULT_TIMEOUT) -> Image.Image | None`:
  validates the domain, builds `f"{HASS_URL}/api/{endpoint}/{quote(entity_name)}"`, fetches with
  the Bearer token and `timeout`, decodes (guards in row 9) and returns a greyscale `'L'` copy.
  On success stores it in a module-level `_last_good_images: dict[str, Image.Image]` (guarded by
  a `threading.Lock`, one entry per entity); on any failure logs and returns the stored image
  for that entity, or None. Missing `HASS_URL`/`HASS_TOKEN` → error log + fallback.
- `reset_image_cache()` test helper.

### `components.py`

- `_draw_image_component(friendly_name, image, width, height, logger, *, title_font_size=None, title_lines=1) -> Image.Image`:
  draws the title on the 2× canvas exactly as the other components do (skipped when
  `title_lines == NO_TITLE_LINES`), LANCZOS-downscales to the tile, then computes the body box
  (below `_title_band_height` + padding, or the whole tile minus padding when the title is
  hidden), fits the image into it (contain), applies autocontrast, dithers with
  `convert('1')` (Floyd–Steinberg), and pastes it centred. Pixels outside the body box are
  never touched by dithering.
- `render_dashboard_image`: `image` branch resolves `timeout` (positive int, capped, warning on
  invalid as `hours`/`columns` do) and sets `data = fetch_entity_image(...)`.
- `tile_components._render_component`: dispatches `image` to `_draw_image_component`.
  `_panel_body_fit` already returns None for it (no body rows).

### `config.py` / `models.py`

- `"image"` added to `VALID_COMPONENT_TYPES`; `_validate_image_component` warns when
  `entity_name` is missing or its domain is not `camera`/`image`.
- `ComponentConfig.type` literal gains `"image"` (`timeout` already exists).

### Docs

README component table + an `image` section (fields, autocontrast always on, letterboxing,
synchronous fetch with last-good fallback); CHANGELOG `[Unreleased]` → Added.

## Testing

- **Unit:** endpoint selection per domain and rejection of other domains; URL quoting; Bearer
  header; timeout passed through and capped; 401/404/URLError/garbage bytes/oversized pixel
  count → last good image or None; `_draw_image_component` output body region contains only
  0/255, title region identical to a no-image render, contain geometry (centred, aspect kept),
  `hide_title` uses the full tile.
- **Integration:** new golden `image_component.png` rendered through `render_dashboard_image`
  with a fake fetched image; all existing goldens pass unchanged without `UPDATE_GOLDEN`; config
  validation warnings via `load_config`-level path.
- **End-to-end:** `do_GET` on `/static/<dash>.png` with the HA proxy faked at `urlopen`:
  final 1-bit PNG shows a dither pattern (mixed black/white) in the body region; repeated for a
  `rotate: 90` dashboard and for `hide_title: true`; a second request where the fetch fails
  still renders the last good picture.
