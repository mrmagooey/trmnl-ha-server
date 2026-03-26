# TRMNL HA Server

Renders Home Assistant dashboards as black-and-white PNG images for TRMNL e-ink devices.

## Configuration

### `server_name` (required)

The externally reachable base URL of your Home Assistant instance **including the port**. TRMNL devices use this URL to fetch dashboard images, so it must be reachable from the devices' network.

Example: `https://myha.duckdns.org:8000`

### `port` (default: 8000)

The port the server listens on. Must match the port in `server_name`.

### `debug` (default: false)

Enable verbose debug logging.

## Dashboard Configuration

Dashboard and device configuration is stored in a `config.yaml` file in this add-on's config directory. Use the **File Editor** add-on to create and edit it.

The file path in File Editor is:
```
/addon_configs/local_trmnl_ha_server/config.yaml
```

See the [README](https://github.com/mrmagooey/trmnl-ha-server) for the full `config.yaml` format including devices, schedules, and dashboard component types.

## Pointing Your TRMNL Device

Set the TRMNL firmware's server URL to:
```
http://<your-ha-ip>:8000
```

The device will call `/api/setup` on first boot and `/api/display` on each refresh.
