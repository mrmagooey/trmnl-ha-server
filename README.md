# Home Assistant E-Ink Display Server

This project is a Python-based server that generates black and white image graphs of Home Assistant entity history, suitable for display on e-ink devices. It provides a simple API for devices to fetch images, cycling through pre-configured dashboards.

## Features

- **Home Assistant Integration**: Fetches historical state data for specified entities from the Home Assistant API.
- **Dynamic Image Generation**: Renders stacked line graphs showing entity state changes over the last 24 hours.
- **E-Ink Optimized**: Converts generated graphs into black and white PNG images, ideal for e-ink displays.
- **Configurable Dashboards**: Define pairs of entities to display together using a simple `config.yaml` file.
- **Simple HTTP API**: Allows devices to request the URL for the next dashboard image in the rotation.
- **Containerized**: Includes a multi-stage `Dockerfile` using `uv` for efficient builds.
- **Kubernetes Ready**: Comes with a `deployment.yaml` manifest for easy deployment, including `ConfigMap` for configuration.

## Configuration

The application is configured through environment variables and a YAML configuration file.

### Environment Variables

- `HASS_URL`: The URL of your Home Assistant instance (e.g., `http://homeassistant.local:8123`).
- `HASS_TOKEN`: A long-lived access token for the Home Assistant API.

### Configuration File (`config.yaml`)

The `config.yaml` file defines the dashboards to be displayed. Each dashboard consists of a name and a list of two entities to be graphed together.

```yaml
dashboards:
  - name: "dash1"
    entities:
      - entity_name: "sensor.your_sensor_1"
        friendly_name: "Sensor 1 Title"
      - entity_name: "sensor.your_sensor_2"
        friendly_name: "Sensor 2 Title"
  - name: "dash2"
    entities:
      - entity_name: "sensor.your_sensor_3"
        friendly_name: "Sensor 3 Title"
      - entity_name: "sensor.your_sensor_4"
        friendly_name: "Sensor 4 Title"
```

## Usage

### Local Development

1.  **Install dependencies:**
    ```bash
    uv pip install -r requirements.txt
    ```

2.  **Set environment variables:**
    ```bash
    export HASS_URL="http://your-hass-url:8123"
    export HASS_TOKEN="your-long-lived-token"
    ```

3.  **Run the server:**
    ```bash
    python3 server.py
    ```

### Docker

1.  **Build the Docker image:**
    ```bash
    docker build -t hass-image-server .
    ```

2.  **Run the container:**
    Create a `.env` file with your `HASS_URL` and `HASS_TOKEN`, then run:
    ```bash
    docker run -p 8000:8000 --env-file .env -v "$(pwd)/config.yaml:/app/config.yaml" hass-image-server
    ```
    *Note: The `-v` flag mounts your local `config.yaml` into the container, allowing you to change it without rebuilding the image.*

### Kubernetes

1.  **Create a secret for the Home Assistant token:**
    ```bash
    kubectl create secret generic hass-credentials --from-literal=token='YOUR_LONG_LIVED_HASS_TOKEN'
    ```

2.  **Apply the deployment manifest:**
    The provided `deployment.yaml` contains both a `ConfigMap` for `config.yaml` and the `Deployment` resource. Customize it with your details and apply it:
    ```bash
    kubectl apply -f deployment.yaml
    ```

3.  **Access the service (e.g., via port-forwarding for testing):**
    ```bash
    kubectl port-forward deployment/hass-image-server 8000:8000
    ```

## API Endpoints

- **`GET /api/display`**
  Returns a JSON object with the URL of the next dashboard image to display. The server cycles through the dashboards defined in `config.yaml`.
  
  **Example Response:**
  ```json
  {
      "filename": "1678886400.0-dash1.png",
      "image_url": "/static/dash1.png",
      "image_url_timeout": 0,
      "reset_firmware": false,
      "update_firmware": false,
      "refresh_rate": 600
  }
  ```

- **`GET /static/<dashboard_name>.png`**
  Serves the generated PNG image for the specified dashboard.

- **`POST /api/logs`**
  A debugging endpoint that logs all request headers and the request body to standard output on the server.
