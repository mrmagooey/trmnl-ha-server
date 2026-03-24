"""Configuration management for trmnl-server.

This module handles loading and validating configuration from YAML files,
as well as dashboard visibility calculations.
"""

from datetime import datetime
from os import environ
from typing import TYPE_CHECKING

import yaml

from models import Config, DashboardConfig, DeviceConfig, ScheduleEntry

if TYPE_CHECKING:
    from logging import Logger

VALID_COMPONENT_TYPES = {"history_graph", "entity", "calendar", "entities", "todo_list"}
VALID_DAYS = {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"}
DAYS_MAP: dict[str, int] = {
    "Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3,
    "Friday": 4, "Saturday": 5, "Sunday": 6,
}


def _validate_config(config: Config, logger: "Logger") -> None:
    """Log warnings for any invalid configuration fields."""
    devices = config.get("devices")
    if devices is not None:
        if not isinstance(devices, list):
            logger.warning("config: 'devices' must be a list")
        else:
            for i, device in enumerate(devices):
                tag = f"device[{i}]"
                dev_id = device.get("id")
                if not dev_id or not isinstance(dev_id, str):
                    logger.warning("config: %s missing or invalid 'id'", tag)
                else:
                    tag = f"device '{dev_id}'"

                schedule = device.get("schedule")
                if schedule is not None and not isinstance(schedule, list):
                    logger.warning("config: %s 'schedule' must be a list", tag)
                elif schedule:
                    for j, entry in enumerate(schedule):
                        etag = f"{tag} schedule[{j}]"
                        dashboard_name = entry.get("dashboard")
                        if not dashboard_name or not isinstance(dashboard_name, str):
                            logger.warning("config: %s missing or invalid 'dashboard'", etag)

                        refresh_rate = entry.get("refresh_rate")
                        if refresh_rate is not None and (not isinstance(refresh_rate, int) or refresh_rate <= 0):
                            logger.warning("config: %s 'refresh_rate' must be a positive integer, got %r", etag, refresh_rate)

                        days_str = entry.get("days_of_the_week")
                        if days_str is not None:
                            parts = [p.strip() for p in str(days_str).split("-", 1)]
                            for part in parts:
                                if part and part not in VALID_DAYS:
                                    logger.warning(
                                        "config: %s unrecognised day %r in 'days_of_the_week'. Valid values: %s",
                                        etag, part, ', '.join(sorted(VALID_DAYS))
                                    )

    dashboards = config.get("dashboards")
    if dashboards is None:
        return
    if not isinstance(dashboards, list):
        logger.warning("config: 'dashboards' must be a list")
        return

    for i, dashboard in enumerate(dashboards):
        tag = f"dashboard[{i}]"

        name = dashboard.get("name")
        if not name or not isinstance(name, str):
            logger.warning("config: %s missing or invalid 'name'", tag)
            tag = f"dashboard[{i}] (unnamed)"
        else:
            tag = f"dashboard '{name}'"

        for j, component in enumerate(dashboard.get("components", [])):
            ctype = component.get("type")
            if ctype is not None and ctype not in VALID_COMPONENT_TYPES:
                logger.warning(
                    "config: %s component[%d] unknown type %r. Valid types: %s",
                    tag, j, ctype, ', '.join(sorted(VALID_COMPONENT_TYPES))
                )


def read_config(logger: "Logger") -> Config:
    """Reads and validates the configuration from config.yaml."""
    config_path: str = environ.get("CONFIG_PATH", "config.yaml")
    try:
        with open(config_path, 'r') as f:
            config: Config = yaml.safe_load(f) or {}
            _validate_config(config, logger)
            return config
    except FileNotFoundError:
        logger.error("'%s' not found.", config_path)
        return {}
    except yaml.YAMLError as e:
        logger.error("Error parsing '%s': %s", config_path, e)
        return {}


def find_device(devices: list[DeviceConfig], device_id: str) -> DeviceConfig | None:
    """Return the DeviceConfig whose id matches device_id, or None."""
    return next((d for d in devices if d.get('id') == device_id), None)


def is_schedule_entry_visible(
    entry: ScheduleEntry,
    now: datetime,
    logger: "Logger",
) -> bool:
    """Checks if a schedule entry should be active based on its time and day rules."""
    days_of_week_str = entry.get('days_of_the_week')
    if days_of_week_str:
        current_day_index: int = now.weekday()

        allowed_days: set[int] = set()
        parts: list[str] = [p.strip() for p in str(days_of_week_str).split('-', 1)]

        if len(parts) == 2:
            start_day = DAYS_MAP.get(parts[0])
            end_day = DAYS_MAP.get(parts[1])
            if start_day is not None and end_day is not None and start_day <= end_day:
                for i in range(start_day, end_day + 1):
                    allowed_days.add(i)
        elif len(parts) == 1:
            day_index = DAYS_MAP.get(parts[0])
            if day_index is not None:
                allowed_days.add(day_index)

        if not allowed_days or current_day_index not in allowed_days:
            return False

    start_time_str = entry.get('start_time')
    end_time_str = entry.get('end_time')
    if start_time_str and end_time_str:
        try:
            start_time = datetime.strptime(start_time_str, "%H:%M").time()
            end_time = datetime.strptime(end_time_str, "%H:%M").time()
            now_time = now.time()

            if start_time <= end_time:  # Same day
                if not (start_time <= now_time < end_time):
                    return False
            else:  # Overnight
                if not (now_time >= start_time or now_time < end_time):
                    return False
        except ValueError:
            logger.error("Invalid time format in schedule entry for dashboard '%s'", entry.get('dashboard'))
            return False

    return True
