"""Home Assistant API client for trmnl-server.

This module handles all communication with the Home Assistant API,
including fetching entity states, history, and calendar events.
"""

import json
from datetime import datetime, timedelta, timezone
from os import environ
from typing import TYPE_CHECKING
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from models import EntityState, HistoryPoint, CalendarEvent

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
            logger.debug(pf(obj))
            return obj
    except HTTPError as e:
        logger.error(f"HTTP Error getting {entity_name}: {e.code} {e.reason}")
        return None
    except URLError as e:
        logger.error(f"URL Error getting {entity_name}: {e.reason}")
        return None


def _fetch_history(
    entity_name: str,
    logger: "Logger",
) -> list[list[HistoryPoint]] | None:
    """Fetches history for an entity from Home Assistant.
    
    Args:
        entity_name: Home Assistant entity ID
        logger: Logger instance for errors
        
    Returns:
        List of history point lists or None if request fails
    """
    if not HASS_URL or not HASS_TOKEN:
        logger.error("HASS_URL and HASS_TOKEN environment variables must be set.")
        return None

    url: str = f"{HASS_URL}/api/history/period?filter_entity_id={entity_name}"
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
        logger.error(f"HTTP Error getting history for {entity_name}: {e.code} {e.reason}")
        return None
    except URLError as e:
        logger.error(f"URL Error getting history for {entity_name}: {e.reason}")
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
        logger.error(f"HTTP Error getting calendar {calendar_id}: {e.code} {e.reason}")
        return []
    except URLError as e:
        logger.error(f"URL Error getting calendar {calendar_id}: {e.reason}")
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
        logger.error(f"HTTP Error getting todo list {entity_name}: {e.code} {e.reason}")
        return []
    except URLError as e:
        logger.error(f"URL Error getting todo list {entity_name}: {e.reason}")
        return []


def _process_history_to_points(
    history: list[list[HistoryPoint]] | None,
) -> list[tuple[datetime, float]]:
    """Processes raw history data into a list of (timestamp, value) tuples.
    
    Args:
        history: Raw history data from Home Assistant
        
    Returns:
        List of (datetime, float) tuples sorted by timestamp
    """
    data_points: list[tuple[datetime, float]] = []
    if not history or not history[0]:
        return data_points

    for state in history[0]:
        try:
            value: float = float(state['state'])
            timestamp: datetime = datetime.fromisoformat(state['last_changed'])
            data_points.append((timestamp, value))
        except (ValueError, TypeError):
            continue
    data_points.sort()
    return data_points
