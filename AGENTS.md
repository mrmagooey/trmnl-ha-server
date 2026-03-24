# Agent Guidelines for trmnl-server

## Build/Lint/Test Commands

This project uses `uv` for Python dependency management and packaging.

```bash
# Install dependencies
uv pip install -r requirements.txt

# Run the server
python3 server.py

# Run all tests
python3 -m unittest test_server.py

# Run a single test
python3 -m unittest test_server.TestServer.test_render_dashboard_image

# Type checking (if mypy is installed)
mypy server.py

# Run with Docker
docker build -t trmnl-server .
docker run -p 8000:8000 --env-file .env trmnl-server
```

## Code Style Guidelines

### Python Version
- Python 3.12.5+ required
- Uses modern type hint syntax (`float | None` instead of `Optional[float]`)

### Imports
- Group imports: stdlib first, then third-party, then local
- Use explicit imports (e.g., `from typing import List, Dict, Any`)
- Standard library imports: `import json`, `import os`
- Third-party: `from PIL import Image`, `import yaml`

### Formatting
- 4 spaces for indentation
- Snake_case for functions and variables
- PascalCase for classes
- UPPER_CASE for module-level constants
- Max line length: ~100 characters (flexible)

### Type Hints
- Use type hints on all function parameters and return types
- Use modern union syntax: `str | float` instead of `Union[str, float]`
- Complex types: `List[Dict[str, Any]]`, `Dict[str, Any]`

### Error Handling
- Use try/except for external operations (HTTP requests, file I/O)
- Log errors with `logger.error()` including context
- Return `None` or empty collections on failure, not exceptions
- Check environment variables before use

### Testing
- Use standard `unittest` framework
- Use `@mock.patch` for mocking external dependencies
- Test files: `test_<module>.py`
- Test class: `Test<Module>` inheriting from `unittest.TestCase`
- Descriptive docstrings for each test method

### Logging
- Use module-level logger: `logger = logging.getLogger(__name__)`
- Log levels: DEBUG for data, ERROR for failures
- Include context in log messages (entity names, URLs)
- Format: `'%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'`

### Documentation
- Docstrings for all public functions
- Google-style docstrings preferred
- Include type info in docstrings for complex parameters

## Project Structure

```
├── server.py           # Entry point - sets up logging and starts server
├── api.py              # HTTP request handlers (APICalls class)
├── components.py       # Image rendering functions for all component types
├── hass_client.py      # Home Assistant API client
├── config.py           # Configuration loading and validation
├── state.py            # Server state management
├── models.py           # Type definitions (TypedDict, Protocol)
├── test_server.py      # Unit tests
├── config.yaml         # Dashboard configuration
├── pyproject.toml      # Project metadata and dependencies
├── requirements.txt    # Runtime dependencies
├── Dockerfile          # Multi-stage container build
└── deployment.yaml     # Kubernetes deployment manifest
```

## Key Dependencies
- `Pillow>=12.0.0`: Image generation
- `PyYAML`: Configuration parsing
- Standard library: `http.server`, `urllib`, `datetime`, `json`

## Environment Variables
- `HASS_URL`: Home Assistant instance URL
- `HASS_TOKEN`: API access token
- `CONFIG_PATH`: Path to config.yaml (default: `config.yaml`)
- `SERVER_NAME`: Server URL for display

## API Endpoints
- `GET /api/display`: Returns next dashboard image URL (JSON)
- `GET /static/<name>.png`: Serves generated PNG images
- `POST /api/logs`: Debug endpoint for logging requests
