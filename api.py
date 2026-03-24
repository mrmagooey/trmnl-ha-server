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

from models import APIDisplayResponse, APISetupResponse, DashboardConfig, RenderData
from state import server_state
from components import (
    render_dashboard_image,
    _create_info_image,
    eink_display,
    tile_components,
)
from config import read_config, is_dashboard_visible
from hass_client import HASS_URL, HASS_TOKEN

if TYPE_CHECKING:
    from logging import Logger

SERVER_NAME: str = environ.get("SERVER_NAME", "https://www.example.com")

_dashboard_index: int = 0
_dashboard_lock: threading.Lock = threading.Lock()


class APICalls(http.server.BaseHTTPRequestHandler):
    """HTTP request handler for the TRMNL server API."""

    def __init__(self, logger: "Logger", *args, **kwargs) -> None:
        """Initialize the request handler with instance-specific state."""
        self.refresh_rate: int = 600
        self.logger = logger
        super().__init__(*args, **kwargs)

    def _get_device_id(self) -> str:
        """Gets the device ID from the ID header, falling back to the request IP.

        The ID header contains the device MAC address sent by TRMNL firmware.
        The IP fallback allows local/test requests without the header to still work.

        Returns:
            Device identifier string
        """
        device_id: str | None = self.headers.get('ID')
        if device_id:
            return device_id
        forwarded_for: str | None = self.headers.get('X-Forwarded-For')
        if forwarded_for:
            return forwarded_for.split(',')[0].strip()
        return self.client_address[0]

    def _handle_api_setup(self) -> None:
        """Handle /api/setup endpoint."""
        from secrets import token_urlsafe
        
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        response: APISetupResponse = {
            "api_key": token_urlsafe(16),
            "friendly_id": "ABC123",
            "image_url": "static/homeassistant.png",
            "message": "Setup successful",
        }
        self.wfile.write(json.dumps(response).encode('utf-8'))

    def _handle_api_display(self) -> None:
        """Handle /api/display endpoint."""
        from datetime import datetime, timedelta
        
        # Capture battery voltage header
        device_id: str = self._get_device_id()
        battery_voltage_header: str | None = self.headers.get('Battery-Voltage')
        if battery_voltage_header is not None:
            try:
                v: float = float(battery_voltage_header)
                server_state.set_battery_voltage(device_id, v)
            except ValueError:
                self.logger.warning(f"Invalid Battery-Voltage header: {battery_voltage_header}")

        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()

        image_url: str = ""
        out_filename: str = "no_dashboards.png"
        from config import read_config
        config = read_config(self.logger)
        dashboards: list[DashboardConfig] = config.get('dashboards', [])
        device_config = config.get('device', {})

        now: datetime = datetime.now()
        self.logger.debug(f"Request from device: {device_id}")

        # Filter dashboards by visibility
        from config import is_dashboard_visible
        time_visible_dashboards: list[DashboardConfig] = [
            d for d in dashboards if is_dashboard_visible(d, now, self.logger)
        ]

        # Filter by allowed device IDs
        visible_dashboards: list[DashboardConfig] = []
        for d in time_visible_dashboards:
            allowed_ids: list[str] | None = d.get('allowed_ids')
            if not allowed_ids or device_id in allowed_ids:
                visible_dashboards.append(d)

        if self.logger.isEnabledFor(10):  # DEBUG
            self.logger.debug("visible dashboards: %s", visible_dashboards)
        refresh_rate: int = self.refresh_rate
        sleep_start_str: str | None = device_config.get('sleep_start')
        sleep_end_str: str | None = device_config.get('sleep_end')

        if visible_dashboards:
            with _dashboard_lock:
                global _dashboard_index
                if _dashboard_index >= len(visible_dashboards):
                    _dashboard_index = 0
                dashboard: DashboardConfig = visible_dashboards[_dashboard_index]
                _dashboard_index = (_dashboard_index + 1) % len(visible_dashboards)

            dashboard_name: str = dashboard.get('name', 'unknown')
            out_filename = f"{dashboard_name}.png"
            image_url = f"{SERVER_NAME}/static/{out_filename}"

            dashboard_refresh_rate: int | None = dashboard.get('refresh_rate')
            if isinstance(dashboard_refresh_rate, int) and dashboard_refresh_rate > 0:
                refresh_rate = dashboard_refresh_rate
            else:
                refresh_rate = self.refresh_rate
        else:
            out_filename = "no_dashboard_visible.png"
            image_url = f"{SERVER_NAME}/static/{out_filename}"

        # Handle sleep schedule
        if sleep_start_str and sleep_end_str:
            try:
                now_time = now.time()
                sleep_start = datetime.strptime(sleep_start_str, "%H:%M").time()
                sleep_end = datetime.strptime(sleep_end_str, "%H:%M").time()

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
                    self.logger.info(f"Device is sleeping. New refresh rate: {refresh_rate} seconds.")

            except ValueError:
                self.logger.error("Invalid time format in device config. Use HH:MM.")

        response: APIDisplayResponse = {
            "filename": f"{time.time()}-{out_filename}",
            "image_url": image_url,
            "image_url_timeout": 0,
            "reset_firmware": False,
            "update_firmware": False,
            "refresh_rate": refresh_rate,
        }
        if self.logger.isEnabledFor(10):  # DEBUG
            from pprint import pformat as pf
            self.logger.debug("display response: %s", pf(response))
        self.wfile.write(json.dumps(response).encode('utf-8'))

    def _handle_static_png(self) -> bool:
        """Handle static PNG image requests.
        
        Returns:
            True if request was handled, False otherwise
        """
        from datetime import datetime
        from PIL import Image
        
        device_id: str = self._get_device_id()
        dashboard_name: str = self.path.split('/')[-1][:-4]

        self.logger.debug(dashboard_name)
        if dashboard_name == 'no_dashboard_visible':
            img: Image.Image = _create_info_image(
                "No dashboard is scheduled for display.",
                800,
                480,
                self.logger,
            )
            temp_io = BytesIO()
            img.save(temp_io, 'PNG')
            temp_io.seek(0)
            img_io: BytesIO = eink_display(temp_io)

            img_io.seek(0, SEEK_END)
            img_size: int = img_io.tell()
            img_io.seek(0)
            self.send_response(200)
            self.send_header("Content-type", "image/png")
            self.send_header("Content-length", str(img_size))
            self.end_headers()
            self.wfile.write(img_io.read())
            return True

        from config import read_config
        config = read_config(self.logger)
        dashboards = config.get('dashboards', [])
        dashboard_to_render: DashboardConfig | None = None
        for dash in dashboards:
            if dash.get('name') == dashboard_name:
                dashboard_to_render = dash
                break

        if dashboard_to_render:
            allowed_ids = dashboard_to_render.get('allowed_ids')
            if allowed_ids and device_id not in allowed_ids:
                self.logger.warning(f"Device {device_id} denied access to dashboard '{dashboard_name}'.")
                return False

        if dashboard_to_render and 'components' in dashboard_to_render:
            t0 = time.perf_counter()
            img_io = render_dashboard_image(dashboard_to_render, self.logger, device_id)
            self.logger.info("rendered '%s' in %.2fs", dashboard_name, time.perf_counter() - t0)
            if img_io:
                img_io.seek(0, SEEK_END)
                img_size = img_io.tell()
                img_io.seek(0)
                self.send_response(200)
                self.send_header("Content-type", "image/png")
                self.send_header("Content-length", str(img_size))
                self.end_headers()
                self.wfile.write(img_io.read())
                return True

        return False

    def do_GET(self) -> None:
        """Handle GET requests."""
        self.logger.info("--- GET Request ---\nPath: %s\nHeaders:\n%s", self.path, str(self.headers))
        try:
            if self.path == '/api/setup':
                self._handle_api_setup()
                return

            if self.path == '/api/display':
                self._handle_api_display()
                return

            if self.path.startswith('/static/') and self.path.endswith('.png'):
                if self._handle_static_png():
                    return

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

            self.logger.info(
                "--- POST Request ---\nPath: %s\nHeaders:\n%s\nBody:\n%s",
                self.path,
                str(self.headers),
                log_body,
            )

            if self.path == '/api/log':
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'OK')
                return

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
