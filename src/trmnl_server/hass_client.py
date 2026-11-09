"""Home Assistant API client for trmnl-server.

This module handles all communication with the Home Assistant API,
including fetching entity states, history, and calendar events.
"""

import http.client
import json
import threading
import time
import warnings
from datetime import datetime, timedelta, timezone
from io import BytesIO
from os import environ
from typing import TYPE_CHECKING
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from PIL import Image

from .models import EntityState, HistoryPoint, CalendarEvent

if TYPE_CHECKING:
    from logging import Logger

# Environment configuration
HASS_URL: str = environ.get("HASS_URL", "http://homeassistant.local:8123")
HASS_TOKEN: str | None = environ.get("HASS_TOKEN")


def _cast_to_numbers(input_value: str) -> str | int | float:
    """Cast a string to int or float if possible.
    
    Args:
        input_value: String to convert
        
    Returns:
        int, float, or original string if conversion fails
    """
    try:
        return int(input_value)
    except ValueError:
        pass
    
    try:
        return float(input_value)
    except ValueError:
        pass

    return input_value


def _select_entity_value(
    state_data: "EntityState | None",
    attribute: str | None,
    entity_name: str,
    logger: "Logger",
) -> str | None:
    """Select the display value for an entity: its state, or a named attribute.

    Args:
        state_data: The fetched entity state, or None if the fetch failed.
        attribute: Name of the attribute to display; falsy means use the state.
        entity_name: Entity id, used only for log context.
        logger: Logger for the missing-attribute warning.

    Returns:
        The state or attribute value as a string (non-scalars are stringified),
        or None if state_data is None or the requested attribute is absent.
        A missing attribute also logs a warning.
    """
    if state_data is None:
        return None
    if not attribute:
        return state_data.get('state')
    attributes = state_data.get('attributes', {})
    if attribute not in attributes:
        logger.warning(
            "Attribute %r not found on %s; rendering blank.",
            attribute, entity_name,
        )
        return None
    return str(attributes[attribute])


def get_entity_state(
    entity_name: str,
    logger: "Logger",
) -> EntityState | None:
    """Gets the state of an entity from Home Assistant.
    
    Args:
        entity_name: Home Assistant entity ID
        logger: Logger instance for errors
        
    Returns:
        Entity state dictionary or None if request fails
    """
    if not HASS_URL or not HASS_TOKEN:
        logger.error("HASS_URL and HASS_TOKEN environment variables must be set.")
        return None

    url: str = f"{HASS_URL}/api/states/{entity_name}"
    req = Request(
        url,
        headers={
            "Authorization": f"Bearer {HASS_TOKEN}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(req) as response:
            data: str = response.read().decode()
            obj: EntityState = json.loads(data)
            from pprint import pformat as pf
            logger.debug("entity state for %s: %s", entity_name, pf(obj))
            return obj
    except HTTPError as e:
        logger.error("HTTP error getting %s: %d %s", entity_name, e.code, e.reason)
        return None
    except URLError as e:
        logger.error("URL error getting %s: %s", entity_name, e.reason)
        return None


def _fetch_history(
    entity_name: str,
    logger: "Logger",
    *,
    start: datetime,
    end: datetime,
) -> list[list[HistoryPoint]] | None:
    """Fetches history for an entity from Home Assistant.

    Args:
        entity_name: Home Assistant entity ID
        logger: Logger instance for errors
        start: Start of the time window (keyword-only)
        end: End of the time window (keyword-only)

    Returns:
        List of history point lists or None if request fails
    """
    if not HASS_URL or not HASS_TOKEN:
        logger.error("HASS_URL and HASS_TOKEN environment variables must be set.")
        return None

    start_iso: str = start.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
    end_iso: str = end.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
    url: str = (
        f"{HASS_URL}/api/history/period/{start_iso}"
        f"?filter_entity_id={entity_name}&end_time={end_iso}"
    )
    req = Request(
        url,
        headers={
            "Authorization": f"Bearer {HASS_TOKEN}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(req) as response:
            data: str = response.read().decode()
            return json.loads(data)
    except HTTPError as e:
        logger.error("HTTP error getting history for %s: %d %s", entity_name, e.code, e.reason)
        return None
    except URLError as e:
        logger.error("URL error getting history for %s: %s", entity_name, e.reason)
        return None


def _fetch_calendar_events(
    calendar_id: str,
    *,
    days: int,
    logger: "Logger",
) -> list[CalendarEvent]:
    """Fetches calendar events from Home Assistant.
    
    Args:
        calendar_id: Home Assistant calendar entity ID
        days: Number of days to fetch (keyword-only argument)
        logger: Logger instance for errors
        
    Returns:
        List of calendar events
    """
    if not HASS_URL or not HASS_TOKEN:
        logger.error("HASS_URL and HASS_TOKEN environment variables must be set.")
        return []

    try:
        now = datetime.now(timezone.utc).astimezone()
        start_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = start_dt + timedelta(days=days)

        # Convert to UTC and format for API
        start_utc = start_dt.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
        end_utc = end_dt.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')

        url: str = f"{HASS_URL}/api/calendars/{calendar_id}?start={start_utc}&end={end_utc}"
        req = Request(
            url,
            headers={
                "Authorization": f"Bearer {HASS_TOKEN}",
                "Content-Type": "application/json",
            },
        )
        with urlopen(req) as response:
            data: str = response.read().decode()
            return json.loads(data)
    except ValueError:
        logger.error("Invalid time format in calendar arguments. Use HH:MM.")
        return []
    except HTTPError as e:
        logger.error("HTTP error getting calendar %s: %d %s", calendar_id, e.code, e.reason)
        return []
    except URLError as e:
        logger.error("URL error getting calendar %s: %s", calendar_id, e.reason)
        return []


def _fetch_todo_list(
    entity_name: str,
    logger: "Logger",
) -> list[dict[str, str]]:
    """Fetches todo list items from Home Assistant.
    
    Args:
        entity_name: Home Assistant todo list entity ID (e.g., 'todo.shopping_list')
        logger: Logger instance for errors
        
    Returns:
        List of todo items with summary and status
    """
    if not HASS_URL or not HASS_TOKEN:
        logger.error("HASS_URL and HASS_TOKEN environment variables must be set.")
        return []

    url: str = f"{HASS_URL}/api/states/{entity_name}"
    req = Request(
        url,
        headers={
            "Authorization": f"Bearer {HASS_TOKEN}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(req) as response:
            data: str = response.read().decode()
            entity_data: dict[str, object] = json.loads(data)
            
            # Todo lists store items in attributes
            attributes: dict[str, object] = entity_data.get('attributes', {})
            items: list[dict[str, str]] = []
            
            # Try to get items from various common todo list formats
            if 'items' in attributes:
                todo_items = attributes['items']
                if isinstance(todo_items, list):
                    for item in todo_items:
                        if isinstance(item, dict):
                            items.append({
                                'summary': item.get('summary', ''),
                                'status': item.get('status', 'needs_action'),
                            })
            
            # Alternative: parse state as comma-separated list
            state = entity_data.get('state', '')
            if state and not items:
                for line in state.split(','):
                    line = line.strip()
                    if line:
                        items.append({
                            'summary': line,
                            'status': 'needs_action',
                        })
            
            return items
    except HTTPError as e:
        logger.error("HTTP error getting todo list %s: %d %s", entity_name, e.code, e.reason)
        return []
    except URLError as e:
        logger.error("URL error getting todo list %s: %s", entity_name, e.reason)
        return []


_HA_GAP_STATES: frozenset[str] = frozenset({'unavailable', 'unknown'})


def _process_history_to_points(
    history: list[list[HistoryPoint]] | None,
) -> list[tuple[datetime, float | None]]:
    """Processes raw history data into a list of (timestamp, value) tuples.

    A value of None marks a point where Home Assistant reported the entity
    as 'unavailable' or 'unknown' — a genuine data gap — as opposed to a
    state that simply failed to parse as a number, which is dropped as
    before.

    Args:
        history: Raw history data from Home Assistant

    Returns:
        List of (datetime, value) tuples sorted by timestamp; value is
        None where the entity was reported unavailable/unknown at that time.
    """
    data_points: list[tuple[datetime, float | None]] = []
    if not history or not history[0]:
        return data_points

    for state in history[0]:
        try:
            timestamp: datetime = datetime.fromisoformat(state['last_changed'])
            if state['state'] in _HA_GAP_STATES:
                data_points.append((timestamp, None))
                continue
            value: float = float(state['state'])
            data_points.append((timestamp, value))
        except (ValueError, TypeError):
            continue
    data_points.sort(key=lambda point: point[0])
    return data_points


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

    Reads the response body in chunks against a total deadline to prevent
    slow-trickling servers from holding the single-threaded server.

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
        deadline: float = time.monotonic() + timeout
        with urlopen(req, timeout=timeout) as response:
            data: bytes = b""
            chunk_size: int = 65_536  # 64 KiB chunks
            while True:
                if time.monotonic() > deadline:
                    logger.error("Timed out fetching image for %s after %ds.", entity_name, timeout)
                    return None
                chunk: bytes = response.read(chunk_size)
                if not chunk:
                    break
                data += chunk
                if len(data) > IMAGE_MAX_BYTES:
                    logger.error("Image for %s exceeds %d bytes.", entity_name, IMAGE_MAX_BYTES)
                    return None
    except HTTPError as e:
        logger.error("HTTP error fetching image for %s: %d %s", entity_name, e.code, e.reason)
        return None
    except URLError as e:
        logger.error("URL error fetching image for %s: %s", entity_name, e.reason)
        return None
    except (OSError, http.client.HTTPException, ValueError) as e:
        logger.error("Error fetching image for %s: %s", entity_name, e)
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
