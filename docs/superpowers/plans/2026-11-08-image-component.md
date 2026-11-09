# Dithered Image Component Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `type: image` dashboard component that shows a Home Assistant `camera.*`/`image.*` entity as a Floyd–Steinberg dithered 1-bit picture.

**Architecture:** `hass_client.fetch_entity_image` fetches the proxy endpoint synchronously (short timeout) and keeps the last good picture per entity as a fallback. `components._draw_image_component` draws the standard title at 2×, LANCZOS-downscales, then pastes a contain-fitted, autocontrasted, dithered picture at final resolution so `eink_display`'s threshold keeps every dot. `render_dashboard_image`, `tile_components` and `config.py` gain an `image` branch.

**Tech Stack:** Python 3.12, Pillow, unittest (run with pytest via `uv`).

**Spec:** `docs/superpowers/specs/2026-11-08-image-component-design.md`

## Global Constraints

- Existing dashboards must render exactly as before: `eink_display`, other components and every existing golden in `tests/golden/` stay byte-identical (run golden tests WITHOUT `UPDATE_GOLDEN`; only the new golden may be created).
- `timeout` default **5s**, capped at **15s**; read ≤ **10 MB** (`10_485_760`); reject images over **16 MP** (`16_000_000`).
- Endpoints: `camera.*` → `/api/camera_proxy/<id>`, `image.*` → `/api/image_proxy/<id>`; entity id URL-quoted; Bearer `HASS_TOKEN`. Never log the token.
- Dithering: Pillow `convert('1')` (Floyd–Steinberg); always `ImageOps.autocontrast(cutoff=1)` first; fit = contain, centred on white, never cropped.
- Code style (AGENTS.md): type hints everywhere, Google-style docstrings, `logger.error` with entity context, return None on failure rather than raising, unittest classes `Test<Thing>` with a docstring per test.
- Test command: `uv run pytest tests/ -q` (full suite must pass at the end of every task).
- Commit trailers on every commit:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01FiygobwBA9XTJk4h8bs8u2
  ```

## Review Focus

1. A transparent PNG (`image.*` entities often are) — expect transparent areas to render white, not black. Pinned in Task 1 (`test_transparent_png_composited_on_white`).
2. An extreme aspect ratio (e.g. 2000×1) — expect no crash, at least a 1-px picture. Pinned in Task 2 (`test_extreme_aspect_ratio_does_not_crash`).
3. A tile too short for any body below the title — expect the title-only tile, no exception. Pinned in Task 2 (`test_no_body_room_returns_title_only`).
4. A slow/dead camera — expect the fetch to give up at `timeout` and show the last good picture. Pinned in Task 1 (`test_timeout_passed_and_fallback_used`) and Task 4 (fallback e2e).
5. A wrong-domain entity (e.g. `sensor.x`) — expect a config warning and the "No data" placeholder, no HTTP request. Pinned in Task 1 (`test_rejects_other_domains_without_request`) and Task 3 (config test).

---

### Task 1: `fetch_entity_image` in `hass_client.py`

**Files:**
- Modify: `src/trmnl_server/hass_client.py` (imports at top; new constants and functions appended at the end of the module)
- Test: `tests/test_hass_client.py` (new class `TestFetchEntityImage`)

**Interfaces:**
- Produces:
  - `IMAGE_DOMAIN_ENDPOINTS: dict[str, str]`, `IMAGE_DEFAULT_TIMEOUT: int = 5`, `IMAGE_MAX_TIMEOUT: int = 15`, `IMAGE_MAX_BYTES: int`, `IMAGE_MAX_PIXELS: int`
  - `fetch_entity_image(entity_name: str, logger: Logger, *, timeout: int = IMAGE_DEFAULT_TIMEOUT) -> PIL.Image.Image | None` — returns a mode `'L'` image
  - `reset_image_cache() -> None` (test helper)

- [ ] **Step 1: Write the failing tests** — append to `tests/test_hass_client.py` (add `from io import BytesIO`, `from urllib.error import HTTPError, URLError`, `from PIL import Image` and `from trmnl_server import hass_client` to the imports):

```python
def _png_bytes(img: "Image.Image") -> bytes:
    buf = BytesIO()
    img.save(buf, 'PNG')
    return buf.getvalue()


class _FakeImageResponse:
    """Context-manager stand-in for urlopen's response."""

    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, n: int = -1) -> bytes:
        return self._body[:n] if n and n > 0 else self._body


class TestFetchEntityImage(unittest.TestCase):
    """Tests for fetch_entity_image."""

    def setUp(self):
        hass_client.reset_image_cache()
        self.logger = mock.Mock(spec=logging.Logger)
        patcher_url = mock.patch.object(hass_client, 'HASS_URL', 'http://hass')
        patcher_token = mock.patch.object(hass_client, 'HASS_TOKEN', 'secret-token')
        patcher_url.start()
        patcher_token.start()
        self.addCleanup(patcher_url.stop)
        self.addCleanup(patcher_token.stop)
        self.addCleanup(hass_client.reset_image_cache)

    def _ok(self, img=None):
        img = img if img is not None else Image.new('RGB', (40, 20), (200, 100, 50))
        return _FakeImageResponse(_png_bytes(img))

    def test_camera_uses_camera_proxy_with_bearer(self):
        """camera.* entities hit /api/camera_proxy with the Bearer token."""
        with mock.patch.object(hass_client, 'urlopen', return_value=self._ok()) as m:
            img = hass_client.fetch_entity_image('camera.front', self.logger)
        req = m.call_args.args[0]
        self.assertEqual(req.full_url, 'http://hass/api/camera_proxy/camera.front')
        self.assertEqual(req.get_header('Authorization'), 'Bearer secret-token')
        self.assertEqual(img.mode, 'L')
        self.assertEqual(img.size, (40, 20))

    def test_image_uses_image_proxy(self):
        """image.* entities hit /api/image_proxy."""
        with mock.patch.object(hass_client, 'urlopen', return_value=self._ok()) as m:
            hass_client.fetch_entity_image('image.map', self.logger)
        self.assertEqual(m.call_args.args[0].full_url, 'http://hass/api/image_proxy/image.map')

    def test_entity_id_is_url_quoted(self):
        """Characters outside an entity id's normal set are percent-encoded."""
        with mock.patch.object(hass_client, 'urlopen', return_value=self._ok()) as m:
            hass_client.fetch_entity_image('camera.a/b c', self.logger)
        self.assertEqual(m.call_args.args[0].full_url, 'http://hass/api/camera_proxy/camera.a%2Fb%20c')

    def test_rejects_other_domains_without_request(self):
        """A non camera/image entity logs an error and never makes a request."""
        with mock.patch.object(hass_client, 'urlopen') as m:
            self.assertIsNone(hass_client.fetch_entity_image('sensor.temp', self.logger))
        m.assert_not_called()
        self.logger.error.assert_called()

    def test_missing_credentials_returns_none(self):
        """No HASS_TOKEN: error logged, no request, None."""
        with mock.patch.object(hass_client, 'HASS_TOKEN', None), \
             mock.patch.object(hass_client, 'urlopen') as m:
            self.assertIsNone(hass_client.fetch_entity_image('camera.front', self.logger))
        m.assert_not_called()

    def test_timeout_passed_and_fallback_used(self):
        """timeout reaches urlopen; a later timeout serves the last good image."""
        with mock.patch.object(hass_client, 'urlopen', return_value=self._ok()) as m:
            first = hass_client.fetch_entity_image('camera.front', self.logger, timeout=7)
        self.assertEqual(m.call_args.kwargs['timeout'], 7)
        with mock.patch.object(hass_client, 'urlopen', side_effect=TimeoutError('slow')):
            second = hass_client.fetch_entity_image('camera.front', self.logger)
        self.assertIsNotNone(second)
        self.assertEqual(second.tobytes(), first.tobytes())

    def test_http_error_logs_status_not_token_and_falls_back(self):
        """401 logs status + entity (never the token) and serves the last good image."""
        with mock.patch.object(hass_client, 'urlopen', return_value=self._ok()):
            hass_client.fetch_entity_image('camera.front', self.logger)
        err = HTTPError('http://hass/x', 401, 'Unauthorized', {}, None)
        with mock.patch.object(hass_client, 'urlopen', side_effect=err):
            img = hass_client.fetch_entity_image('camera.front', self.logger)
        self.assertIsNotNone(img)
        logged = ' '.join(str(a) for c in self.logger.error.call_args_list for a in c.args)
        self.assertIn('401', logged)
        self.assertIn('camera.front', logged)
        self.assertNotIn('secret-token', logged)

    def test_failure_with_no_history_returns_none(self):
        """A URLError before any success yields None."""
        with mock.patch.object(hass_client, 'urlopen', side_effect=URLError('down')):
            self.assertIsNone(hass_client.fetch_entity_image('camera.front', self.logger))

    def test_garbage_bytes_fall_back(self):
        """Undecodable bytes log an error and fall back."""
        with mock.patch.object(hass_client, 'urlopen', return_value=_FakeImageResponse(b'not an image')):
            self.assertIsNone(hass_client.fetch_entity_image('camera.front', self.logger))
        self.logger.error.assert_called()

    def test_oversized_body_rejected(self):
        """A body over IMAGE_MAX_BYTES is rejected without decoding."""
        big = b'x' * (hass_client.IMAGE_MAX_BYTES + 1)
        with mock.patch.object(hass_client, 'urlopen', return_value=_FakeImageResponse(big)):
            self.assertIsNone(hass_client.fetch_entity_image('camera.front', self.logger))

    def test_too_many_pixels_rejected(self):
        """An image whose header exceeds IMAGE_MAX_PIXELS is rejected."""
        with mock.patch.object(hass_client, 'IMAGE_MAX_PIXELS', 100), \
             mock.patch.object(hass_client, 'urlopen', return_value=self._ok()):
            self.assertIsNone(hass_client.fetch_entity_image('camera.front', self.logger))

    def test_transparent_png_composited_on_white(self):
        """Fully transparent pixels become white, not black."""
        rgba = Image.new('RGBA', (10, 10), (0, 0, 0, 0))
        with mock.patch.object(hass_client, 'urlopen', return_value=self._ok(rgba)):
            img = hass_client.fetch_entity_image('image.map', self.logger)
        self.assertEqual(img.getextrema(), (255, 255))

    def test_fallback_is_a_copy(self):
        """Mutating a returned image never corrupts the stored fallback."""
        with mock.patch.object(hass_client, 'urlopen', return_value=self._ok()):
            first = hass_client.fetch_entity_image('camera.front', self.logger)
        first.paste(0, (0, 0, 40, 20))
        with mock.patch.object(hass_client, 'urlopen', side_effect=URLError('down')):
            second = hass_client.fetch_entity_image('camera.front', self.logger)
        self.assertNotEqual(second.getextrema(), (0, 0))
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_hass_client.py -q -k FetchEntityImage`
Expected: FAIL / ERROR (`fetch_entity_image` not defined).

- [ ] **Step 3: Implement** — in `src/trmnl_server/hass_client.py` add imports `import threading`, `import warnings`, `from io import BytesIO`, `from urllib.parse import quote`, `from PIL import Image` (stdlib group then third-party, per AGENTS.md), then append:

```python
# Image components: HA serves a camera's or image entity's current picture
# through these proxy endpoints, authenticated with the same Bearer token.
IMAGE_DOMAIN_ENDPOINTS: dict[str, str] = {"camera": "camera_proxy", "image": "image_proxy"}
# The render runs inside a single-threaded server's request, so a slow camera
# must give up quickly; the last good picture covers the gap.
IMAGE_DEFAULT_TIMEOUT: int = 5
IMAGE_MAX_TIMEOUT: int = 15
IMAGE_MAX_BYTES: int = 10_485_760
IMAGE_MAX_PIXELS: int = 16_000_000

# entity id -> last successfully decoded picture ('L' mode), one per entity.
_last_good_images: dict[str, Image.Image] = {}
_image_lock = threading.Lock()


def _decode_image(data: bytes, entity_name: str, logger: "Logger") -> Image.Image | None:
    """Decode untrusted image bytes into a greyscale picture.

    Rejects pictures over IMAGE_MAX_PIXELS from the header, before any pixel
    data is decoded, and treats Pillow's decompression-bomb warning as an
    error. Transparent pixels are composited onto white.

    Args:
        data: Raw response body.
        entity_name: Entity id, for log context.
        logger: Logger for decode failures.

    Returns:
        A mode 'L' image, or None if the bytes are not a usable picture.
    """
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as img:
                width, height = img.size
                if width * height > IMAGE_MAX_PIXELS:
                    logger.error(
                        "Image for %s is %dx%d, over the %d pixel limit.",
                        entity_name, width, height, IMAGE_MAX_PIXELS,
                    )
                    return None
                img.draft("L", (2048, 2048))  # JPEG decodes at reduced size; no-op otherwise
                if img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info:
                    rgba = img.convert("RGBA")
                    flattened = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
                    flattened.alpha_composite(rgba)
                    return flattened.convert("L")
                return img.convert("L")
    except Exception as e:  # noqa: BLE001 - untrusted bytes must never crash a render
        logger.error("Could not decode image for %s: %s", entity_name, e)
        return None


def _download_entity_image(entity_name: str, logger: "Logger", timeout: int) -> Image.Image | None:
    """Fetch and decode an entity's current picture, without any fallback.

    Args:
        entity_name: A camera.* or image.* entity id.
        logger: Logger for request and decode failures.
        timeout: Socket timeout in seconds.

    Returns:
        A mode 'L' image, or None on any failure.
    """
    domain: str = entity_name.split(".", 1)[0] if isinstance(entity_name, str) else ""
    endpoint: str | None = IMAGE_DOMAIN_ENDPOINTS.get(domain)
    if endpoint is None:
        logger.error("Image entity %r must be a camera.* or image.* entity.", entity_name)
        return None
    if not HASS_URL or not HASS_TOKEN:
        logger.error("HASS_URL and HASS_TOKEN environment variables must be set.")
        return None

    url: str = f"{HASS_URL}/api/{endpoint}/{quote(entity_name, safe='')}"
    req = Request(url, headers={"Authorization": f"Bearer {HASS_TOKEN}"})
    try:
        with urlopen(req, timeout=timeout) as response:
            data: bytes = response.read(IMAGE_MAX_BYTES + 1)
    except HTTPError as e:
        logger.error("HTTP error fetching image for %s: %d %s", entity_name, e.code, e.reason)
        return None
    except URLError as e:
        logger.error("URL error fetching image for %s: %s", entity_name, e.reason)
        return None
    except OSError as e:  # socket timeouts during read
        logger.error("Error fetching image for %s: %s", entity_name, e)
        return None
    if len(data) > IMAGE_MAX_BYTES:
        logger.error("Image for %s exceeds %d bytes.", entity_name, IMAGE_MAX_BYTES)
        return None
    return _decode_image(data, entity_name, logger)


def fetch_entity_image(
    entity_name: str,
    logger: "Logger",
    *,
    timeout: int = IMAGE_DEFAULT_TIMEOUT,
) -> Image.Image | None:
    """Get a camera or image entity's current picture, greyscale.

    Fetches synchronously from the entity's HA proxy endpoint. On success the
    picture is remembered; on any failure the last good picture for the
    entity is returned instead, so an outage keeps showing the old picture.

    Args:
        entity_name: A camera.* or image.* entity id.
        logger: Logger for failures.
        timeout: Socket timeout in seconds.

    Returns:
        A mode 'L' image (a copy the caller may modify), or None if the fetch
        failed and no earlier picture exists.
    """
    image = _download_entity_image(entity_name, logger, timeout)
    with _image_lock:
        if image is not None:
            _last_good_images[entity_name] = image
            return image.copy()
        fallback = _last_good_images.get(entity_name)
    if fallback is None:
        return None
    logger.warning("Showing the last good image for %s.", entity_name)
    return fallback.copy()


def reset_image_cache() -> None:
    """Forget every remembered picture. Test-only helper."""
    with _image_lock:
        _last_good_images.clear()
```

- [ ] **Step 4: Run tests** — `uv run pytest tests/test_hass_client.py -q` → all PASS; then `uv run pytest tests/ -q` → all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/trmnl_server/hass_client.py tests/test_hass_client.py
git commit -m "feat: fetch camera/image entity pictures from Home Assistant"   # plus trailers
```

---

### Task 2: `_draw_image_component` in `components.py`

**Files:**
- Modify: `src/trmnl_server/components.py` (import `ImageOps`; constant `IMAGE_PADDING` beside `NO_TITLE_CONTENT_TOP`; new functions placed directly before `def _todo_capacity`)
- Test: `tests/test_components.py` (new class `TestDrawImageComponent`)

**Interfaces:**
- Consumes: nothing from Task 1 (takes any PIL image).
- Produces:
  - `IMAGE_PADDING: int = 10`
  - `_image_body_box(width: int, height: int, title_font_size: int | None, title_lines: int, logger) -> tuple[int, int, int, int]` — `(left, top, right, bottom)` in unscaled tile px
  - `_dither_to_box(image: Image.Image, box_w: int, box_h: int) -> Image.Image` — mode `'1'`
  - `_draw_image_component(friendly_name: str, image: Image.Image, width: int, height: int, logger, *, title_font_size: int | None = None, title_lines: int = 1) -> Image.Image` — RGB, size `(width, height)`

- [ ] **Step 1: Write the failing tests** — append to `tests/test_components.py` (import the four names above from `trmnl_server.components`, plus `NO_TITLE_CONTENT_TOP` and `NO_TITLE_LINES`; add `ImageOps` to the existing `from PIL import Image, ImageChops, ImageDraw, ImageFont` line):

```python
class TestDrawImageComponent(unittest.TestCase):
    """Tests for the dithered image panel."""

    def setUp(self):
        self.logger = mock.Mock(spec=logging.Logger)

    def _body(self, tile, box):
        return tile.crop(box)

    def test_body_pixels_are_pure_black_or_white(self):
        """Every pixel in the body box is 0 or 255 on every channel."""
        src = Image.linear_gradient('L').resize((300, 200))
        tile = _draw_image_component('Cam', src, 400, 300, self.logger, title_font_size=30)
        box = _image_body_box(400, 300, 30, 1, self.logger)
        colours = {px for px in self._body(tile, box).getdata()}
        self.assertTrue(colours <= {(0, 0, 0), (255, 255, 255)}, colours)

    def test_mid_grey_is_dithered_not_thresholded(self):
        """A uniform mid-grey becomes a mix of black and white dots."""
        src = Image.new('L', (200, 200), 128)
        tile = _draw_image_component('Cam', src, 400, 300, self.logger, title_font_size=30)
        body = self._body(tile, _image_body_box(400, 300, 30, 1, self.logger)).convert('L')
        black = sum(1 for p in body.getdata() if p == 0)
        self.assertGreater(black / (body.width * body.height), 0.2)
        self.assertLess(black / (body.width * body.height), 0.8)

    def test_title_region_independent_of_picture(self):
        """Pixels above the body box are the same whatever the picture is."""
        a = _draw_image_component('Cam', Image.new('L', (50, 50), 0), 400, 300, self.logger, title_font_size=30)
        b = _draw_image_component('Cam', Image.new('L', (50, 50), 255), 400, 300, self.logger, title_font_size=30)
        top = _image_body_box(400, 300, 30, 1, self.logger)[1]
        self.assertEqual(a.crop((0, 0, 400, top)).tobytes(), b.crop((0, 0, 400, top)).tobytes())
        self.assertIsNotNone(ImageOps.invert(a.crop((0, 0, 400, top)).convert('L')).getbbox(),
                             'title ink expected')

    def test_contain_keeps_aspect_and_centres(self):
        """A 2:1 black picture fills the box width and is vertically centred."""
        left, top, right, bottom = _image_body_box(400, 300, 30, 1, self.logger)
        tile = _draw_image_component('Cam', Image.new('L', (200, 100), 0), 400, 300,
                                     self.logger, title_font_size=30)
        ink = ImageOps.invert(tile.crop((left, top, right, bottom)).convert('L')).getbbox()
        box_w, box_h = right - left, bottom - top
        ink_w, ink_h = ink[2] - ink[0], ink[3] - ink[1]
        expected_h = min(box_h, round(box_w / 2))
        expected_w = min(box_w, round(expected_h * 2))
        self.assertAlmostEqual(ink_w, expected_w, delta=1)
        self.assertAlmostEqual(ink_h, expected_h, delta=1)
        self.assertAlmostEqual(ink[0], box_w - ink[2], delta=1)
        self.assertAlmostEqual(ink[1], box_h - ink[3], delta=1)

    def test_hide_title_uses_top_inset(self):
        """With no title the body starts at NO_TITLE_CONTENT_TOP."""
        box = _image_body_box(400, 300, None, NO_TITLE_LINES, self.logger)
        self.assertEqual(box, (IMAGE_PADDING, NO_TITLE_CONTENT_TOP, 400 - IMAGE_PADDING, 300 - IMAGE_PADDING))

    def test_two_line_title_pushes_body_down(self):
        """A two-line title band starts the body lower than a one-line one."""
        one = _image_body_box(400, 300, 30, 1, self.logger)[1]
        two = _image_body_box(400, 300, 30, 2, self.logger)[1]
        self.assertGreater(two, one)

    def test_extreme_aspect_ratio_does_not_crash(self):
        """A 2000x1 picture still renders at least one pixel high."""
        out = _dither_to_box(Image.new('L', (2000, 1), 0), 380, 200)
        self.assertEqual(out.mode, '1')
        self.assertGreaterEqual(out.height, 1)
        self.assertLessEqual(out.width, 380)

    def test_no_body_room_returns_title_only(self):
        """A tile too short for a body returns the tile without raising."""
        tile = _draw_image_component('Cam', Image.new('L', (50, 50), 0), 400, 40,
                                     self.logger, title_font_size=30)
        self.assertEqual(tile.size, (400, 40))

    def test_output_size_and_mode(self):
        """The tile is RGB at the requested size."""
        tile = _draw_image_component('Cam', Image.new('L', (50, 50), 0), 266, 220, self.logger)
        self.assertEqual((tile.mode, tile.size), ('RGB', (266, 220)))
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_components.py -q -k DrawImageComponent` → ImportError/FAIL.

- [ ] **Step 3: Implement** — change `from PIL import Image, ImageDraw, ImageFont` to `from PIL import Image, ImageDraw, ImageFont, ImageOps`; add below `NO_TITLE_CONTENT_TOP`:

```python
# Unscaled inset around an image panel's picture, on the sides and bottom.
IMAGE_PADDING: int = 10
```

Add before `def _todo_capacity`:

```python
def _image_body_box(
    width: int,
    height: int,
    title_font_size: int | None,
    title_lines: int,
    logger: "Logger",
) -> tuple[int, int, int, int]:
    """The area of an image panel the picture is fitted into.

    Args:
        width: Unscaled tile width
        height: Unscaled tile height
        title_font_size: Resolved title size (None means the default)
        title_lines: Title line count, or NO_TITLE_LINES for a hidden title
        logger: Logger instance

    Returns:
        (left, top, right, bottom) in unscaled tile pixels; may be empty
    """
    if title_lines == NO_TITLE_LINES:
        top: int = NO_TITLE_CONTENT_TOP
    else:
        band: int = _title_band_height(
            title_font_size or COMPONENT_TITLE_FONT_SIZE, title_lines, logger
        )
        top = 5 + band + TITLE_BAND_GAP
    return (
        IMAGE_PADDING,
        top,
        max(IMAGE_PADDING, width - IMAGE_PADDING),
        max(top, height - IMAGE_PADDING),
    )


def _dither_to_box(image: Image.Image, box_w: int, box_h: int) -> Image.Image:
    """Fit a picture inside a box and dither it to pure black and white.

    The picture keeps its aspect ratio and is never cropped. Contrast is
    stretched first, since flat camera frames otherwise dither to grey mush.

    Args:
        image: Source picture, any mode
        box_w: Box width in final pixels (> 0)
        box_h: Box height in final pixels (> 0)

    Returns:
        A mode '1' image no larger than the box, Floyd–Steinberg dithered
    """
    grey: Image.Image = image.convert('L')
    ratio: float = min(box_w / grey.width, box_h / grey.height)
    size: tuple[int, int] = (
        max(1, min(box_w, round(grey.width * ratio))),
        max(1, min(box_h, round(grey.height * ratio))),
    )
    fitted: Image.Image = ImageOps.autocontrast(grey.resize(size, Image.LANCZOS), cutoff=1)
    return fitted.convert('1')  # Pillow's default dither is Floyd–Steinberg


def _draw_image_component(
    friendly_name: str,
    image: Image.Image,
    width: int,
    height: int,
    logger: "Logger",
    *,
    title_font_size: int | None = None,
    title_lines: int = 1,
) -> Image.Image:
    """Draws a picture panel: a title above a dithered picture.

    The title is drawn at COMPONENT_SCALE and downscaled like every other
    panel. The picture is dithered at final resolution and pasted after the
    downscale, so its dots are already pure black and white and survive
    eink_display's threshold unchanged.

    Args:
        friendly_name: Display name for the component
        image: The picture to show
        width: Component width in pixels
        height: Component height in pixels
        logger: Logger instance
        title_font_size: Title size resolved by the caller (None: default)
        title_lines: Title lines, or NO_TITLE_LINES to draw no title

    Returns:
        Rendered PIL Image
    """
    scale: int = COMPONENT_SCALE
    large_width: int = width * scale
    img = Image.new('RGB', (large_width, height * scale), color='white')
    d = ImageDraw.Draw(img)
    if title_lines != NO_TITLE_LINES:
        font_title = _load_font((title_font_size or COMPONENT_TITLE_FONT_SIZE) * scale, logger)
        _draw_panel_title(d, friendly_name, font_title, large_width, title_lines, scale)
    tile: Image.Image = img.resize((width, height), Image.LANCZOS)

    left, top, right, bottom = _image_body_box(width, height, title_font_size, title_lines, logger)
    box_w, box_h = right - left, bottom - top
    if box_w <= 0 or box_h <= 0:
        logger.warning("No room for the picture in %s's %dx%d panel.", friendly_name, width, height)
        return tile

    dithered: Image.Image = _dither_to_box(image, box_w, box_h)
    tile.paste(
        dithered.convert('RGB'),
        (left + (box_w - dithered.width) // 2, top + (box_h - dithered.height) // 2),
    )
    return tile
```

- [ ] **Step 4: Run tests** — `uv run pytest tests/test_components.py -q` then `uv run pytest tests/ -q` → all PASS.

- [ ] **Step 5: Commit** — `git add src/trmnl_server/components.py tests/test_components.py && git commit -m "feat: draw a dithered picture panel"` (plus trailers).

---

### Task 3: Wire `image` into rendering, config and docs

**Files:**
- Modify: `src/trmnl_server/components.py` — `render_dashboard_image` (new `elif component_type == 'image':` before the final `else:` of the per-component loop) and `tile_components._render_component` (new `elif component_type == 'image':` before its `else:`)
- Modify: `src/trmnl_server/config.py` — `VALID_COMPONENT_TYPES`, new `_validate_image_component` after `_validate_url_component`, call site after `if ctype == "url":`
- Modify: `src/trmnl_server/models.py` — `ComponentConfig.type` literal gains `"image"`
- Modify: `README.md` (component table row + `#### image component` section after the `url` section), `CHANGELOG.md` (`## [Unreleased]` → `### Added`)
- Test: `tests/test_golden.py` (`test_image_panel`), `tests/test_config.py` (`TestValidateImageComponent`), `tests/test_components.py` (`TestRenderImageBranch`)

**Interfaces:**
- Consumes: `hass_client.fetch_entity_image`, `IMAGE_DEFAULT_TIMEOUT`, `IMAGE_MAX_TIMEOUT`, `IMAGE_DOMAIN_ENDPOINTS` (Task 1); `_draw_image_component` (Task 2).

- [ ] **Step 1: Write the failing tests.**

`tests/test_components.py`:

```python
class TestRenderImageBranch(unittest.TestCase):
    """render_dashboard_image wiring for type: image."""

    def setUp(self):
        self.logger = mock.Mock(spec=logging.Logger)

    @mock.patch('trmnl_server.hass_client.fetch_entity_image')
    def test_timeout_resolved_and_capped(self, mock_fetch):
        """timeout defaults to 5, is capped at 15, and bad values warn and default."""
        mock_fetch.return_value = Image.new('L', (40, 20), 128)
        for given, expected in ((None, 5), (8, 8), (99, 15), ('x', 5), (True, 5), (0, 5)):
            comp = {'type': 'image', 'entity_name': 'camera.front', 'friendly_name': 'Cam'}
            if given is not None:
                comp['timeout'] = given
            render_dashboard_image({'name': 'd', 'components': [comp]}, self.logger)
            self.assertEqual(mock_fetch.call_args.kwargs['timeout'], expected, given)
            self.assertEqual(mock_fetch.call_args.args[0], 'camera.front')

    @mock.patch('trmnl_server.hass_client.fetch_entity_image', return_value=None)
    def test_no_picture_renders_no_data_placeholder(self, _mock_fetch):
        """A failed fetch with no fallback draws the standard placeholder."""
        from trmnl_server import components as components_module
        with mock.patch.object(components_module, '_create_info_image',
                               wraps=components_module._create_info_image) as spy:
            render_dashboard_image({'name': 'd', 'components': [
                {'type': 'image', 'entity_name': 'camera.front', 'friendly_name': 'Cam'}]}, self.logger)
        self.assertIn('No data for\nCam', [c.args[0] for c in spy.call_args_list])
```

`tests/test_config.py` (import `_validate_config` is already there):

```python
class TestValidateImageComponent(unittest.TestCase):
    """Config validation for type: image."""

    def _warnings(self, component):
        logger = mock.Mock(spec=logging.Logger)
        _validate_config({'dashboards': [{'name': 'd', 'components': [component]}]}, logger)
        return ' '.join(c.args[0] % c.args[1:] for c in logger.warning.call_args_list)

    def test_valid_camera_and_image_no_warning(self):
        """camera.* and image.* entities validate cleanly, and 'image' is a known type."""
        for entity in ('camera.front', 'image.map'):
            self.assertEqual(self._warnings({'type': 'image', 'entity_name': entity,
                                             'friendly_name': 'x'}), '')

    def test_missing_entity_warns(self):
        """A missing entity_name warns."""
        self.assertIn("missing 'entity_name'", self._warnings({'type': 'image', 'friendly_name': 'x'}))

    def test_wrong_domain_warns(self):
        """A sensor entity warns that it must be camera.* or image.*."""
        self.assertIn('camera.* or image.*', self._warnings(
            {'type': 'image', 'entity_name': 'sensor.temp', 'friendly_name': 'x'}))

    def test_bad_timeout_warns(self):
        """A non-positive or non-int timeout warns; an over-cap one notes the cap."""
        self.assertIn("'timeout' must be a positive integer", self._warnings(
            {'type': 'image', 'entity_name': 'camera.a', 'friendly_name': 'x', 'timeout': 0}))
        self.assertIn('capped at 15', self._warnings(
            {'type': 'image', 'entity_name': 'camera.a', 'friendly_name': 'x', 'timeout': 30}))
```

(If `_validate_config`'s signature differs from `(config, logger)`, adapt the helper to the real one — check `src/trmnl_server/config.py`. If test_config.py does not import `logging`/`mock`, add them.)

`tests/test_golden.py` — inside `TestGoldenImages`:

```python
    @mock.patch('trmnl_server.hass_client.get_entity_state')
    @mock.patch('trmnl_server.hass_client.fetch_entity_image')
    def test_image_panel(self, mock_fetch_image, mock_get_entity_state):
        """An image panel beside an entity panel: dithered picture under a title."""
        mock_fetch_image.return_value = Image.linear_gradient('L').resize((320, 180))
        mock_get_entity_state.return_value = {'state': '21.5', 'attributes': {}}
        dashboard = {
            'name': 'image_panel',
            'title': 'Image',
            'components': [
                {'type': 'image', 'entity_name': 'camera.front', 'friendly_name': 'Front door'},
                {'type': 'entity', 'entity_name': 'sensor.t', 'friendly_name': 'Temp'},
            ],
        }
        with mock.patch('datetime.datetime', mock_datetime()):
            img_io = render_dashboard_image(dashboard, mock_logger)
        assert_golden(img_io, 'image_panel')
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_components.py tests/test_config.py -q -k "Image"` → FAIL.

- [ ] **Step 3: Implement.**

`render_dashboard_image`, before the final `else:` of the component loop:

```python
        elif component_type == 'image':
            from .hass_client import fetch_entity_image, IMAGE_DEFAULT_TIMEOUT, IMAGE_MAX_TIMEOUT
            image_timeout = component.get('timeout', IMAGE_DEFAULT_TIMEOUT)
            if isinstance(image_timeout, bool) or not isinstance(image_timeout, int) or image_timeout <= 0:
                logger.warning(
                    "Invalid 'timeout' (%r) for %s; defaulting to %d.",
                    image_timeout, component.get('friendly_name'), IMAGE_DEFAULT_TIMEOUT,
                )
                image_timeout = IMAGE_DEFAULT_TIMEOUT
            data = fetch_entity_image(
                component.get('entity_name', ''), logger,
                timeout=min(image_timeout, IMAGE_MAX_TIMEOUT),
            )
```

`_render_component`, before its final `else:`:

```python
        elif component_type == 'image':
            return _draw_image_component(
                friendly_name,
                data,  # type: ignore[arg-type]
                tile_width,
                tile_height,
                logger,
                title_font_size=title_font_size,
                title_lines=title_lines,
            )
```

`config.py`: add `from .hass_client import IMAGE_DOMAIN_ENDPOINTS, IMAGE_MAX_TIMEOUT` to the local imports; `VALID_COMPONENT_TYPES = {"history_graph", "entity", "calendar", "entities", "todo_list", "url", "image"}`; after `_validate_url_component`:

```python
def _validate_image_component(
    component: "ComponentConfig",
    tag: str,
    index: int,
    logger: "Logger",
) -> None:
    """Warn about invalid fields on an image component."""
    entity = component.get("entity_name")
    if not entity:
        logger.warning("config: %s component[%d] type 'image' is missing 'entity_name'", tag, index)
    elif not isinstance(entity, str) or entity.split(".", 1)[0] not in IMAGE_DOMAIN_ENDPOINTS:
        logger.warning(
            "config: %s component[%d] 'entity_name' must be a camera.* or image.* entity, got %r",
            tag, index, entity,
        )

    timeout = component.get("timeout")
    if timeout is not None:
        if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout <= 0:
            logger.warning(
                "config: %s component[%d] 'timeout' must be a positive integer, got %r",
                tag, index, timeout,
            )
        elif timeout > IMAGE_MAX_TIMEOUT:
            logger.warning(
                "config: %s component[%d] 'timeout' %d is capped at %d seconds",
                tag, index, timeout, IMAGE_MAX_TIMEOUT,
            )
```

and at the call site:

```python
            if ctype == "image":
                _validate_image_component(component, tag, j, logger)
```

`models.py`: `type: Literal["history_graph", "entity", "calendar", "entities", "todo_list", "url", "image"]`.

README — table row after `url`:

```markdown
| `image` | A camera or image entity's current picture, dithered to black and white | `entity_name` (`camera.*` or `image.*`), `friendly_name` |
```

and a section after the `url` component section (before `## Usage`):

````markdown
#### `image` component

Shows the current picture of a Home Assistant `camera.*` or `image.*` entity, fetched from `/api/camera_proxy/<entity>` or `/api/image_proxy/<entity>` with the same token as every other request.

- **`entity_name`** (required): a `camera.*` or `image.*` entity. Any other domain logs a config warning and the panel shows "No data".
- **`timeout`** (optional, default `5` seconds, capped at `15`): how long a fetch may take. The fetch happens while the dashboard renders, so a fresh picture is shown on every refresh; keep this short, because the device waits for the render.
- **`hide_title`** and **`large_display`** work the same as for any other component type.

The picture is scaled to fit the panel with its aspect ratio kept — letterboxed on white, never cropped — then its contrast is stretched (always on) and it is Floyd–Steinberg dithered to black and white so shades of grey show as dot density. If a fetch fails, the last picture fetched successfully since the server started is shown instead; before the first success the panel shows "No data". Responses over 10 MB or pictures over 16 megapixels are rejected. Transparent areas render white.

```yaml
- type: image
  entity_name: "camera.front_door"
  friendly_name: "Front door"
  large_display: true
```
````

CHANGELOG under `## [Unreleased]`:

```markdown
### Added
- `image` component: shows a Home Assistant camera or image entity's current picture, dithered to black and white so greys come through as dot patterns on the e-ink screen. Fetched fresh on every render with a short `timeout` (default 5s, max 15s); the last good picture is shown if a fetch fails.
```

- [ ] **Step 4: Run tests** — `uv run pytest tests/ -q` (no `UPDATE_GOLDEN`). The first run creates `tests/golden/image_panel.png`; open it with the Read tool and confirm the left tile shows a title and a dithered gradient. Run again → all PASS, and `git status --short tests/golden` shows ONLY the new `image_panel.png` (every existing golden unchanged). `*.png` is gitignored, so add it with `git add -f`.

- [ ] **Step 5: Commit** — `git add -f tests/golden/image_panel.png` plus the modified files; `git commit -m "feat: image component renders HA camera/image entities dithered"` (plus trailers).

---

### Task 4: End-to-end test through the HTTP server

**Files:**
- Create: `tests/test_image_component_e2e.py`

**Interfaces:**
- Consumes: everything above; `trmnl_server.server.create_handler_class`, `trmnl_server.api.SERVER_NAME`, `trmnl_server.hass_client.HASS_URL/HASS_TOKEN/reset_image_cache`.

- [ ] **Step 1: Write the test** — a real localhost "Home Assistant" serving a PNG at `/api/camera_proxy/camera.front`, then real `GET /static/<dash>.png` requests against this server:

```python
"""End-to-end test for the image component — real HTTP on both sides.

A localhost stand-in for Home Assistant serves a mid-grey PNG from the camera
proxy endpoint; this server's /static/<dashboard>.png route is then fetched
over HTTP and the final 1-bit PNG is inspected for a dither pattern.
"""

import http.server
import os
import shutil
import socketserver
import tempfile
import threading
import unittest
import urllib.request
from io import BytesIO
from logging import getLogger
from unittest import mock

from PIL import Image

from trmnl_server import api, hass_client
from trmnl_server.server import create_handler_class

HEADER_HEIGHT = 40  # render_dashboard_image's TOP_MARGIN


def _grey_png() -> bytes:
    buf = BytesIO()
    Image.new('L', (320, 240), 128).save(buf, 'PNG')
    return buf.getvalue()


class _FakeHomeAssistant(http.server.BaseHTTPRequestHandler):
    """Serves the PNG at the camera proxy path; fails when server.fail is set."""

    def do_GET(self):
        self.server.paths.append(self.path)
        self.server.auth.append(self.headers.get('Authorization'))
        if self.server.fail or self.path != '/api/camera_proxy/camera.front':
            self.send_response(500)
            self.end_headers()
            return
        body = _grey_png()
        self.send_response(200)
        self.send_header('Content-type', 'image/png')
        self.send_header('Content-length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


def _black_fraction(img: Image.Image, box: tuple[int, int, int, int]) -> float:
    region = img.convert('L').crop(box)
    return sum(1 for p in region.getdata() if p == 0) / (region.width * region.height)


class TestImageComponentEndToEnd(unittest.TestCase):
    """GET /static/<dash>.png -> HA camera proxy -> dithered 1-bit PNG."""

    def setUp(self):
        hass_client.reset_image_cache()
        self.tmp_dir = tempfile.mkdtemp()

        self.ha = socketserver.ThreadingTCPServer(('127.0.0.1', 0), _FakeHomeAssistant)
        self.ha.paths, self.ha.auth, self.ha.fail = [], [], False
        threading.Thread(target=self.ha.serve_forever, daemon=True).start()
        ha_url = f"http://127.0.0.1:{self.ha.server_address[1]}"
        for patcher in (mock.patch.object(hass_client, 'HASS_URL', ha_url),
                        mock.patch.object(hass_client, 'HASS_TOKEN', 'e2e-token')):
            patcher.start()
            self.addCleanup(patcher.stop)

        self.config_path = os.path.join(self.tmp_dir, 'config.yaml')
        with open(self.config_path, 'w') as f:
            f.write(
                "devices:\n"
                '  - id: "AA:BB:CC:DD:EE:FF"\n'
                "    schedule:\n"
                "      - dashboard: cam\n"
                "dashboards:\n"
                "  - name: cam\n"
                "    title: Cam\n"
                "    components:\n"
                "      - type: image\n"
                "        entity_name: camera.front\n"
                "        friendly_name: Front door\n"
                "  - name: cam_rotated\n"
                "    rotate: 90\n"
                "    components:\n"
                "      - type: image\n"
                "        entity_name: camera.front\n"
                "        friendly_name: Front door\n"
                "  - name: cam_untitled\n"
                "    components:\n"
                "      - type: image\n"
                "        entity_name: camera.front\n"
                "        friendly_name: Front door\n"
                "        hide_title: true\n"
            )
        self._orig_config_path = os.environ.get('CONFIG_PATH')
        os.environ['CONFIG_PATH'] = self.config_path

        Handler = create_handler_class(getLogger('test_image_component_e2e'))
        self.httpd = socketserver.TCPServer(('127.0.0.1', 0), Handler)
        self.port = self.httpd.server_address[1]
        self._orig_server_name = api.SERVER_NAME
        api.SERVER_NAME = f"http://127.0.0.1:{self.port}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.ha.shutdown()
        self.ha.server_close()
        api.SERVER_NAME = self._orig_server_name
        if self._orig_config_path is None:
            os.environ.pop('CONFIG_PATH', None)
        else:
            os.environ['CONFIG_PATH'] = self._orig_config_path
        shutil.rmtree(self.tmp_dir, ignore_errors=True)
        hass_client.reset_image_cache()

    def _get(self, dashboard: str) -> Image.Image:
        url = f"http://127.0.0.1:{self.port}/static/AA-BB-CC-DD-EE-FF/{dashboard}.png"
        with urllib.request.urlopen(url, timeout=30) as resp:
            self.assertEqual(resp.status, 200)
            img = Image.open(BytesIO(resp.read()))
            img.load()
        return img

    def test_picture_is_dithered_in_final_png(self):
        """Mid-grey arrives as ~50% black dots in the body; token sent to HA."""
        img = self._get('cam')
        self.assertEqual(img.size, (800, 480))
        self.assertEqual(self.ha.paths, ['/api/camera_proxy/camera.front'])
        self.assertEqual(self.ha.auth, ['Bearer e2e-token'])
        frac = _black_fraction(img, (300, 200, 500, 400))
        self.assertGreater(frac, 0.3)
        self.assertLess(frac, 0.7)

    def test_rotated_dashboard_keeps_dither(self):
        """A rotate: 90 dashboard is 480x800 and the dots survive rotation."""
        img = self._get('cam_rotated')
        self.assertEqual(img.size, (480, 800))
        frac = _black_fraction(img, (100, 250, 300, 550))
        self.assertGreater(frac, 0.3)
        self.assertLess(frac, 0.7)

    def test_hide_title_starts_picture_near_top(self):
        """With hide_title the dithered picture reaches up to just below the header."""
        img = self._get('cam_untitled')
        frac = _black_fraction(img, (300, HEADER_HEIGHT + 15, 500, HEADER_HEIGHT + 45))
        self.assertGreater(frac, 0.3)

    def test_failed_fetch_shows_last_good_picture(self):
        """After HA starts failing, the next render still shows the dithered picture."""
        first = self._get('cam')
        self.ha.fail = True
        second = self._get('cam')
        self.assertEqual(len(self.ha.paths), 2)
        box = (0, HEADER_HEIGHT, 800, 480)
        self.assertEqual(first.crop(box).tobytes(), second.crop(box).tobytes())
```

The body sampling boxes assume a single full-size tile (one component fills 800×440 below the 40px header; rotated, the canvas is 480×800 after rotation). If a box lands on the letterbox margin because of the picture's 4:3 aspect, adjust the box to sit inside the picture's ink and say so in the report — do not loosen the 0.3–0.7 bounds.

- [ ] **Step 2: Run** — `uv run pytest tests/test_image_component_e2e.py -v` → all PASS (the feature is already implemented; if any test fails, the failure is a real bug in Tasks 1–3 — fix it at its source and add a regression test at the matching level).

- [ ] **Step 3: Full suite** — `uv run pytest tests/ -q` → all PASS; `git status --short tests/golden` shows nothing modified.

- [ ] **Step 4: Commit** — `git add tests/test_image_component_e2e.py && git commit -m "test: image component end to end through /static"` (plus trailers).
