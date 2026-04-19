"""HTTP API handlers for trmnl-server.

This module contains the HTTP request handler and all endpoint logic.
"""

import http.server
import json
import threading
import time
from io import BytesIO, SEEK_END
from os import environ
from typing import TYPE_CHECKING
from urllib.parse import quote

from models import APIDisplayResponse, APISetupResponse, DashboardConfig, DeviceConfig, ScheduleEntry, RenderData
from state import server_state
from components import (
    render_dashboard_image,
    _create_info_image,
    eink_display,
    tile_components,
)
from config import read_config, is_schedule_entry_visible, find_device, _coerce_time
from hass_client import HASS_URL, HASS_TOKEN

if TYPE_CHECKING:
    from logging import Logger

SERVER_NAME: str = environ.get("SERVER_NAME", "https://www.example.com")

_device_indices: dict[str, int] = {}
_dashboard_lock: threading.Lock = threading.Lock()


class APICalls(http.server.BaseHTTPRequestHandler):
    """HTTP request handler for the TRMNL server API."""

    def __init__(self, logger: "Logger", *args, **kwargs) -> None:
        """Initialize the request handler with instance-specific state."""
        self.refresh_rate: int = 600
        self.logger = logger
        super().__init__(*args, **kwargs)

    def _device_label(self, device_config: "DeviceConfig | None", device_id: "str | None") -> str:
        """Returns 'name (id)' if the device has a name, otherwise just the id."""
        if device_config is not None:
            name: str | None = device_config.get('name')
            if name:
                return f"{name} ({device_id})"
        return device_id

    def _get_device_id(self) -> str | None:
        """Gets the device ID from the ID header sent by TRMNL firmware.

        Returns:
            Device MAC address string, or None if the header is absent.
        """
        return self.headers.get('ID') or None

    def _handle_api_setup(self) -> None:
        """Handle /api/setup endpoint."""
        from secrets import token_urlsafe
        
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        response: APISetupResponse = {
            "status": 200,
            "api_key": token_urlsafe(16),
            "friendly_id": "ABC123",
            "image_url": "static/homeassistant.png",
            "filename": "empty_state",
        }
        self.wfile.write(json.dumps(response).encode('utf-8'))

    def _handle_api_display(self) -> None:
        """Handle /api/display endpoint."""
        from datetime import datetime, timedelta

        # Capture battery voltage header
        device_id: str | None = self._get_device_id()
        battery_voltage_header: str | None = self.headers.get('Battery-Voltage')
        if battery_voltage_header is not None and device_id is not None:
            try:
                v: float = float(battery_voltage_header)
                server_state.set_battery_voltage(device_id, v)
            except ValueError:
                self.logger.warning("Invalid Battery-Voltage header: %s", battery_voltage_header)

        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()

        out_filename: str = "device_not_found.png"
        image_url: str = f"{SERVER_NAME}/static/{out_filename}"
        refresh_rate: int = self.refresh_rate

        if device_id is None:
            self.logger.warning("Rejected /api/display request with no ID header")
        else:
            config = read_config(self.logger)
            devices: list[DeviceConfig] = config.get('devices', [])

            now: datetime = datetime.now()
            device_config: DeviceConfig | None = find_device(devices, device_id)
            label: str = self._device_label(device_config, device_id)

            self.logger.debug("Request from device: %s", label)

            if device_config is None:
                self.logger.warning("Device %s not found in devices config.", label)
                image_url = f"{SERVER_NAME}/static/device_id/{device_id.replace(':', '-')}.png"
            else:
                out_filename = "no_dashboard_visible.png"
                image_url = f"{SERVER_NAME}/static/{out_filename}"

                schedule: list[ScheduleEntry] = device_config.get('schedule', [])
                visible_entries: list[ScheduleEntry] = [
                    e for e in schedule if is_schedule_entry_visible(e, now, self.logger)
                ]

                if self.logger.isEnabledFor(10):  # DEBUG
                    self.logger.debug("visible schedule entries: %s", visible_entries)

                if visible_entries:
                    with _dashboard_lock:
                        idx = _device_indices.get(device_id, 0)
                        if idx >= len(visible_entries):
                            idx = 0
                        entry: ScheduleEntry = visible_entries[idx]
                        _device_indices[device_id] = (idx + 1) % len(visible_entries)

                    dashboard_name: str = entry.get('dashboard', 'unknown')
                    out_filename = f"{quote(dashboard_name)}.png"
                    encoded_id: str = device_id.replace(':', '-')
                    image_url = f"{SERVER_NAME}/static/{quote(encoded_id, safe='')}/{out_filename}"
                    self.logger.info("Device %s → dashboard '%s'", label, dashboard_name)

                    entry_refresh_rate: int | None = entry.get('refresh_rate')
                    if isinstance(entry_refresh_rate, int) and entry_refresh_rate > 0:
                        refresh_rate = entry_refresh_rate

                sleep_start_str: str | None = device_config.get('sleep_start')
                sleep_end_str: str | None = device_config.get('sleep_end')
                if sleep_start_str and sleep_end_str:
                    try:
                        now_time = now.time()
                        sleep_start = datetime.strptime(_coerce_time(sleep_start_str), "%H:%M").time()
                        sleep_end = datetime.strptime(_coerce_time(sleep_end_str), "%H:%M").time()

                        is_sleeping: bool = False
                        if sleep_start > sleep_end:  # Overnight
                            if now_time >= sleep_start or now_time < sleep_end:
                                is_sleeping = True
                        else:  # Same day
                            if sleep_start <= now_time < sleep_end:
                                is_sleeping = True

                        if is_sleeping:
                            sleep_end_dt: datetime = now.replace(
                                hour=sleep_end.hour,
                                minute=sleep_end.minute,
                                second=0,
                                microsecond=0,
                            )
                            if now >= sleep_end_dt:
                                sleep_end_dt += timedelta(days=1)

                            refresh_rate = int((sleep_end_dt - now).total_seconds())
                            self.logger.info("Device %s is sleeping. Refresh rate: %d seconds.", label, refresh_rate)

                    except ValueError:
                        self.logger.error("Invalid time format in device config. Use HH:MM.")

        response: APIDisplayResponse = {
            "status": 0,
            "filename": f"{time.time()}-{out_filename}",
            "image_url": image_url,
            "image_url_timeout": 0,
            "reset_firmware": False,
            "update_firmware": False,
            "firmware_url": None,
            "refresh_rate": str(refresh_rate),
        }
        if self.logger.isEnabledFor(10):  # DEBUG
            from pprint import pformat as pf
            self.logger.debug("display response: %s", pf(response))
        self.wfile.write(json.dumps(response).encode('utf-8'))

    def _send_png(self, img_io: BytesIO) -> None:
        """Send a PNG BytesIO as a 200 image/png response."""
        img_io.seek(0, SEEK_END)
        img_size: int = img_io.tell()
        img_io.seek(0)
        self.send_response(200)
        self.send_header("Content-type", "image/png")
        self.send_header("Content-length", str(img_size))
        self.end_headers()
        self.wfile.write(img_io.read())

    def _serve_info_image(self, message: str) -> bool:
        """Render and serve a plain text info image."""
        from PIL import Image

        img: Image.Image = _create_info_image(message, 800, 480, self.logger)
        temp_io = BytesIO()
        img.save(temp_io, 'PNG')
        temp_io.seek(0)
        self._send_png(eink_display(temp_io))
        return True

    def _handle_static_png(self) -> bool:
        """Handle static PNG image requests.
        
        Returns:
            True if request was handled, False otherwise
        """
        from datetime import datetime
        from urllib.parse import unquote

        device_id: str | None = self._get_device_id()
        path: str = unquote(self._parse_path())

        # /static/device_id/<id>.png — show the device its own ID
        if path.startswith('/static/device_id/'):
            path_device_id: str = path[len('/static/device_id/'):-4].replace('-', ':')
            return self._serve_info_image(f"Device ID: {path_device_id}")

        # /static/<encoded_id>/<dashboard>.png — device ID embedded in path
        path_parts = path[len('/static/'):].split('/')
        if len(path_parts) == 2:
            device_id = path_parts[0].replace('-', ':')
            dashboard_name: str = path_parts[1][:-4]
        else:
            dashboard_name = path.split('/')[-1][:-4]

        self.logger.debug("static request: %s", dashboard_name)
        info_messages: dict[str, str] = {
            'no_dashboard_visible': "No dashboard is scheduled for display.",
            'device_not_found': f"Device {device_id or 'unknown'} not found.",
        }
        if dashboard_name in info_messages:
            return self._serve_info_image(info_messages[dashboard_name])

        config = read_config(self.logger)
        dashboards = config.get('dashboards', [])

        if device_id is not None:
            devices: list[DeviceConfig] = config.get('devices', [])
            device_config: DeviceConfig | None = find_device(devices, device_id)
            label: str = self._device_label(device_config, device_id)
            if device_config is not None:
                schedule = device_config.get('schedule', [])
                if not any(e.get('dashboard') == dashboard_name for e in schedule):
                    self.logger.warning("Device %s denied access to dashboard '%s'.", label, dashboard_name)
                    return False
            else:
                self.logger.warning("Device %s not found in devices config.", label)
                return False

        dashboard_to_render: DashboardConfig | None = None
        for dash in dashboards:
            if dash.get('name') == dashboard_name:
                dashboard_to_render = dash
                break

        if dashboard_to_render and 'components' in dashboard_to_render:
            t0 = time.perf_counter()
            device_rotate = device_config.get('rotate') if device_config is not None else None
            img_io = render_dashboard_image(dashboard_to_render, self.logger, device_id, device_rotate)
            self.logger.info("rendered '%s' in %.2fs", dashboard_name, time.perf_counter() - t0)
            if img_io:
                self._send_png(img_io)
                return True

        return False

    def log_message(self, format: str, *args: object) -> None:
        """Route BaseHTTPRequestHandler access logs through our logger."""
        self.logger.debug("%s - " + format, self.client_address[0], *args)

    def log_error(self, format: str, *args: object) -> None:
        """Route BaseHTTPRequestHandler error logs (including 400s) through our logger."""
        self.logger.warning("%s - " + format, self.client_address[0], *args)

    def _parse_path(self) -> str:
        """Return the request path with query string, extra leading slashes, and trailing slashes stripped."""
        return ('/' + self.path.split('?')[0].lstrip('/')).rstrip('/')

    def do_GET(self) -> None:
        """Handle GET requests."""
        self.logger.debug("GET %s\nHeaders:\n%s", self.path, str(self.headers))
        try:
            path: str = self._parse_path()

            if path == '/api/setup':
                self._handle_api_setup()
                return

            if path == '/api/display':
                self._handle_api_display()
                return

            if path.startswith('/static/') and path.endswith('.png'):
                if self._handle_static_png():
                    return

            self.logger.warning("GET 404: %s (raw: %s)", path, self.path)
            self.send_response(404)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Not Found')
        except Exception:
            self.logger.exception("Unhandled error handling GET %s", self.path)
            try:
                self.send_response(500)
                self.send_header('Content-type', 'text/plain')
                self.end_headers()
                self.wfile.write(b'Internal Server Error')
            except Exception:
                pass

    def do_POST(self) -> None:
        """Handle POST requests."""
        try:
            content_length: int = int(self.headers.get('Content-Length', 0))
            post_data: bytes = self.rfile.read(content_length)
            body: str = post_data.decode('utf-8', errors='ignore')

            log_body: str = body
            if body:
                try:
                    from pprint import pformat as pf
                    log_body = pf(json.loads(body))
                except json.JSONDecodeError:
                    pass  # Not json, log as is

            self.logger.debug(
                "POST %s\nHeaders:\n%s\nBody:\n%s",
                self.path,
                str(self.headers),
                log_body,
            )

            path: str = self._parse_path()

            if path == '/api/setup':
                self._handle_api_setup()
                return

            if path == '/api/log':
                self.logger.info(
                    "POST /api/log\nHeaders:\n%s\nBody:\n%s",
                    str(self.headers),
                    log_body,
                )
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'OK')
                return

            self.logger.warning("POST 404: %s (raw: %s)", path, self.path)
            self.send_response(404)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Not Found')
        except Exception:
            self.logger.exception("Unhandled error handling POST %s", self.path)
            try:
                self.send_response(500)
                self.send_header('Content-type', 'text/plain')
                self.end_headers()
                self.wfile.write(b'Internal Server Error')
            except Exception:
                pass
