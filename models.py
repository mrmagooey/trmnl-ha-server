"""Type definitions for trmnl-server.

This module contains TypedDict definitions and Protocol classes for
type-safe configuration and component handling.
"""

from typing import TypedDict, Protocol, runtime_checkable, Literal, Required, NotRequired
from datetime import datetime
from io import BytesIO
from PIL.Image import Image as PILImage


class ScheduleEntry(TypedDict, total=False):
    """A schedule entry linking a dashboard to display times for a device."""
    dashboard: Required[str]
    start_time: str
    end_time: str
    days_of_the_week: str
    refresh_rate: int


class CalendarArguments(TypedDict, total=False):
    """Arguments for calendar components."""
    calendar_id: str
    days: int


class EntityItem(TypedDict):
    """Single entity entry in an entities list."""
    entity_name: str
    friendly_name: str


class TodoItem(TypedDict, total=False):
    """Single todo item from a todo list."""
    uid: str
    summary: str
    status: Literal["needs_action", "completed"]
    description: str


class ComponentConfig(TypedDict, total=False):
    """Configuration for a single dashboard component."""
    entity_name: str
    friendly_name: str
    type: Literal["history_graph", "entity", "calendar", "entities", "todo_list"]
    arguments: CalendarArguments
    entities: list[EntityItem]
    large_display: bool


class DashboardConfig(TypedDict, total=False):
    """Configuration for a dashboard."""
    name: Required[str]
    title: str
    components: list[ComponentConfig]
    portrait: bool
    rotate: int


class DeviceConfig(TypedDict, total=False):
    """Per-device configuration."""
    id: Required[str]
    name: str
    sleep_start: str
    sleep_end: str
    rotate: int
    schedule: list[ScheduleEntry]


class Config(TypedDict, total=False):
    """Root configuration structure."""
    devices: list[DeviceConfig]
    dashboards: list[DashboardConfig]


class EntityState(TypedDict, total=False):
    """Home Assistant entity state response."""
    state: str
    attributes: dict[str, object]
    last_changed: str
    last_updated: str


class HistoryPoint(TypedDict):
    """Single point in entity history."""
    state: str
    last_changed: str


class CalendarEventStart(TypedDict, total=False):
    """Calendar event start time specification."""
    dateTime: str
    date: str


class CalendarEventEnd(TypedDict, total=False):
    """Calendar event end time specification."""
    dateTime: str
    date: str


class CalendarEvent(TypedDict, total=False):
    """Calendar event from Home Assistant."""
    summary: str
    start: CalendarEventStart
    end: CalendarEventEnd


@runtime_checkable
class ComponentRenderer(Protocol):
    """Protocol for component rendering functions."""

    def __call__(
        self,
        friendly_name: str,
        data: object,
        width: int,
        height: int,
    ) -> PILImage:
        """Render a component to an image.

        Args:
            friendly_name: Display name for the component
            data: Component-specific data (history points, entity state, etc.)
            width: Width of the component in pixels
            height: Height of the component in pixels

        Returns:
            Rendered PIL Image
        """
        ...


class RenderData(TypedDict):
    """Data structure for component rendering pipeline."""
    type: str
    friendly_name: str
    data: object
    large_display: bool


class APIDisplayResponse(TypedDict):
    """JSON response structure for /api/display endpoint."""
    status: int
    filename: str
    image_url: str
    image_url_timeout: int
    reset_firmware: bool
    update_firmware: bool
    firmware_url: str | None
    refresh_rate: str


class APISetupResponse(TypedDict):
    """JSON response structure for /api/setup endpoint."""
    status: int
    api_key: str
    friendly_id: str
    image_url: str
    filename: str
