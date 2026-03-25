# Home Assistant E-Ink Display Server

A Python HTTP server that fetches data from Home Assistant and renders black-and-white PNG dashboards for e-ink devices (such as TRMNL). Each device has its own schedule controlling which dashboard is shown at which time of day.

> **Affordable hardware**: DIY TRMNL devices using Seeed Studio hardware are a more affordable alternative to commercial options.

## Features

- **Per-device scheduling**: Each device has an independent schedule mapping dashboards to time windows and days of the week.
- **Multiple component types**: Dashboards can mix history graphs, single entity values, entity lists, calendar events, and todo lists.
- **Sleep windows**: Devices can be configured with a sleep window; during sleep the server returns a refresh rate equal to the seconds until wake-up.
- **Home Assistant integration**: Fetches entity state, history, calendar events, and todo lists from the Home Assistant API.
- **E-ink optimized**: All images are rendered in black and white at double resolution then downscaled.
- **Containerized**: Multi-stage `Dockerfile` using `uv` for efficient builds.
- **Kubernetes ready**: `deployment.yaml` manifest with `ConfigMap` for configuration.

## Configuration

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `HASS_URL` | Yes | URL of your Home Assistant instance (e.g. `http://homeassistant.local:8123`) |
| `HASS_TOKEN` | Yes | Long-lived access token for the Home Assistant API |
| `SERVER_NAME` | Yes | Externally reachable base URL of this server (e.g. `https://trmnl.example.com`). Used to build `image_url` in `/api/display` responses. |
| `CONFIG_PATH` | No | Path to the config file (default: `config.yaml`) |
| `PORT` | No | Port to listen on (default: `8000`) |

### Configuration File (`config.yaml`)

The config file has two top-level sections: `devices` and `dashboards`.

#### `devices`

Each entry defines a device, its optional sleep window, and a schedule of dashboards to show.

```yaml
devices:
  - id: "AA:BB:CC:DD:EE:FF"   # MAC address sent by device in the 'ID' header
    name: "Living Room"        # Optional: human-readable name (used in log messages)
    sleep_start: "23:00"       # Optional: start of sleep window (HH:MM local time)
    sleep_end: "06:00"         # Optional: end of sleep window (HH:MM local time)
    schedule:
      - dashboard: weekday_morning   # References dashboards[].name
        start_time: "06:00"          # Inclusive start (HH:MM local time)
        end_time: "10:00"            # Exclusive end (HH:MM local time)
        days_of_the_week: "Monday-Friday"  # Range or single day
        refresh_rate: 600            # Seconds between device refreshes
      - dashboard: night
        start_time: "18:00"
        end_time: "22:00"
        days_of_the_week: "Monday-Sunday"
        refresh_rate: 600
```

`days_of_the_week` accepts a range (`"Monday-Friday"`) or a single day (`"Saturday"`). Days: Monday, Tuesday, Wednesday, Thursday, Friday, Saturday, Sunday.

During the `sleep_start`/`sleep_end` window the server overrides `refresh_rate` to the number of seconds until `sleep_end`, so the device wakes up at the right time.

#### `dashboards`

Each dashboard defines content only — scheduling is configured per-device above.

```yaml
dashboards:
  - name: weekday_morning    # Used as the image filename: /static/weekday_morning.png
    title: "Morning"         # Optional title rendered at the top of the image
    # portrait: true         # Optional: rotate 90° clockwise for portrait orientation
    components:
      - type: calendar
        friendly_name: "Shared Calendar"
        arguments:
          calendar_id: "calendar.family"
          days: 2

      - type: entity
        friendly_name: "Outside Temp"
        entity_name: "sensor.outside_temperature"

      - type: history_graph
        friendly_name: "Power Usage"
        entity_name: "sensor.power_consumption"

  - name: night
    title: "Night"
    components:
      - type: entities
        friendly_name: "Evening Summary"
        entities:
          - entity_name: "sensor.indoor_temp"
            friendly_name: "Indoor"
          - entity_name: "sensor.outdoor_temp"
            friendly_name: "Outdoor"
```

#### Component Types

| Type | Description | Required fields |
|------|-------------|-----------------|
| `history_graph` | Line graph of a numeric entity's history over the last 24 hours | `entity_name`, `friendly_name` |
| `entity` | Single current state value for an entity | `entity_name`, `friendly_name` |
| `entities` | List of current state values for multiple entities | `friendly_name`, `entities` (list of `entity_name`/`friendly_name`) |
| `calendar` | Upcoming calendar events | `friendly_name`, `arguments.calendar_id`, `arguments.days` |
| `todo_list` | Incomplete items from a Home Assistant todo list | `entity_name`, `friendly_name` |

Set `large_display: true` on one component to give it the top half of the screen; remaining components are tiled along the bottom.

## Usage

### Local Development

1. **Install dependencies:**
   ```bash
   uv pip install -r requirements.txt
   ```

2. **Set environment variables:**
   ```bash
   export HASS_URL="http://your-hass-url:8123"
   export HASS_TOKEN="your-long-lived-token"
   export SERVER_NAME="http://localhost:8000"
   ```

3. **Run the server:**
   ```bash
   python3 server.py
   ```

### Docker

1. **Build the Docker image:**
   ```bash
   docker build -t trmnl-ha-server .
   ```

2. **Run the container:**
   Create a `.env` file with your environment variables, then run:
   ```bash
   docker run -p 8000:8000 --env-file .env -v "$(pwd)/config.yaml:/app/config.yaml" trmnl-ha-server
   ```
   The `-v` flag mounts your local `config.yaml` into the container so you can change it without rebuilding the image.

### Kubernetes

1. **Create a secret for the Home Assistant token:**
   ```bash
   kubectl create secret generic hass-credentials --from-literal=token='YOUR_LONG_LIVED_HASS_TOKEN'
   ```

2. **Apply the deployment manifest:**
   Customize `deployment.yaml` with your details and apply:
   ```bash
   kubectl apply -f deployment.yaml
   ```

3. **Access the service (e.g. via port-forwarding for testing):**
   ```bash
   kubectl port-forward deployment/hass-image-server 8000:8000
   ```

## API Endpoints

### `GET /api/setup`

Called by a device on first boot. Returns a setup confirmation.

**Example response:**
```json
{
    "api_key": "randomly_generated_token",
    "friendly_id": "ABC123",
    "image_url": "static/homeassistant.png",
    "message": "Setup successful"
}
```

### `GET /api/display`

Returns the next dashboard for the requesting device. The server finds the device by its `ID` header, filters its schedule to entries active at the current time and day, and cycles through them on successive calls.

**Device headers read:**

| Header | Description |
|--------|-------------|
| `ID` | Device MAC address (primary identifier) |
| `Battery-Voltage` | Optional battery voltage, rendered on the dashboard image |
| `X-Forwarded-For` | Used as device ID if `ID` header is absent (proxy environments) |

If the device is not found in `config.yaml`, or no schedule entries are active, `image_url` points to a generated "no dashboard scheduled" image.

**Example response:**
```json
{
    "filename": "1678886400.0-weekday_morning.png",
    "image_url": "https://trmnl.example.com/static/weekday_morning.png",
    "image_url_timeout": 0,
    "reset_firmware": false,
    "update_firmware": false,
    "refresh_rate": 600
}
```

### `GET /static/<dashboard_name>.png`

Renders and serves the PNG image for the named dashboard. The device must have that dashboard in its schedule; unrecognised devices or out-of-schedule requests receive a 404.

### `POST /api/log`

Debug endpoint. Logs the request headers and body to the server log and returns `200 OK`. Useful for capturing firmware diagnostic payloads.
