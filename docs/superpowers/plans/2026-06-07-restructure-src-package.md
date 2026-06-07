# src/ Package Restructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the flat top-level Python code into a `src/trmnl_server/` package, with tests in `tests/`, the font bundled inside the package, and sample files in `examples/` — without changing any runtime behavior.

**Architecture:** `src/` package layout. The app launches via `python -m trmnl_server.server` (no install); Docker copies `src/` and sets `PYTHONPATH=/app/src`. Intra-package imports become relative (`from .models import X`). The font is resolved relative to `__file__`. Tests resolve the package via pytest's `pythonpath = ["src"]`.

**Tech Stack:** Python 3.12, Pillow, PyYAML, stdlib `http.server`/`socketserver`, pytest (dev), Docker.

**Branch:** `restructure-src-package` (already created and checked out).

**Baseline (measured 2026-06-07):** `116 passed`. This is the green target. Every task ends green-to-green; any new failure is a regression introduced by the move.

**Canonical test command (used everywhere below):**
```bash
uv run --with pytest --with pyyaml pytest -q
```
(pytest and PyYAML are not in the project env, so `--with` supplies them ephemerally.)

---

## File Structure (end state)

```
src/trmnl_server/
  __init__.py            # new, empty package marker
  __main__.py            # new, enables `python -m trmnl_server`
  api.py  components.py  config.py
  hass_client.py  models.py  server.py  state.py   # moved from repo root
  assets/NotoSans-Regular.ttf                       # moved from repo root
tests/
  test_api.py  test_components.py  test_config.py
  test_golden.py  test_hass_client.py  test_server.py
  test_server_module.py  test_state.py              # moved from repo root
  golden/                # auto-created by test_golden.py on first run
examples/
  config.yaml            # moved from repo root
  deployment.yaml        # moved from repo root
Dockerfile  entrypoint.sh  pyproject.toml  .dockerignore   # edited in place
README.md  AGENTS.md     # edited in place
```

---

## Task 1: Confirm the green baseline

**Files:** none (verification only).

- [ ] **Step 1: Confirm clean tree on the feature branch**

Run: `git status --short && git branch --show-current`
Expected: no uncommitted changes (other than the already-committed spec), branch is `restructure-src-package`.

- [ ] **Step 2: Run the full suite and record the count**

Run: `uv run --with pytest --with pyyaml pytest -q`
Expected: `116 passed`. If the number differs, STOP and investigate before moving any files — the baseline must be green and known.

---

## Task 2: Move source + tests into the package (atomic, green-to-green)

This task is one commit because partial states are not runnable: the moment modules live under `trmnl_server`, the top-level test imports break, so source and tests move together.

**Files:**
- Create: `src/trmnl_server/__init__.py`, `src/trmnl_server/__main__.py`
- Move: `{api,components,config,hass_client,models,server,state}.py` → `src/trmnl_server/`
- Move: `NotoSans-Regular.ttf` → `src/trmnl_server/assets/`
- Move: `test_*.py` (8 files) → `tests/`
- Modify: `src/trmnl_server/api.py`, `components.py`, `config.py`, `hass_client.py`, `server.py` (relative imports)
- Modify: `src/trmnl_server/components.py` (font path)
- Modify: all `tests/test_*.py` (import + patch targets)
- Modify: `pyproject.toml` (pytest pythonpath)

- [ ] **Step 1: Create the directory skeleton and move files with `git mv`**

```bash
mkdir -p src/trmnl_server/assets tests
git mv api.py components.py config.py hass_client.py models.py server.py state.py src/trmnl_server/
git mv NotoSans-Regular.ttf src/trmnl_server/assets/
git mv test_api.py test_components.py test_config.py test_golden.py test_hass_client.py test_server.py test_server_module.py test_state.py tests/
```

- [ ] **Step 2: Add the empty package marker**

Create `src/trmnl_server/__init__.py` with a single line:

```python
"""TRMNL Home Assistant e-ink display server package."""
```

- [ ] **Step 3: Add the package entry point**

Create `src/trmnl_server/__main__.py`:

```python
"""Allow `python -m trmnl_server` to start the server."""
from trmnl_server.server import main

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Rewrite intra-package imports to relative**

```bash
sed -i -E "s/^from (models|state|components|config|hass_client|api) import/from .\1 import/" \
  src/trmnl_server/api.py src/trmnl_server/components.py src/trmnl_server/config.py \
  src/trmnl_server/hass_client.py src/trmnl_server/server.py
```

Verify the result is exactly these relative imports (and nothing else changed):

Run: `grep -rnE "^from \.(models|state|components|config|hass_client|api) import" src/trmnl_server/`
Expected lines include:
- `src/trmnl_server/api.py: from .models import APIDisplayResponse, ...`
- `src/trmnl_server/api.py: from .state import server_state`
- `src/trmnl_server/api.py: from .components import (`
- `src/trmnl_server/api.py: from .config import read_config, is_schedule_entry_visible, find_device, _coerce_time`
- `src/trmnl_server/api.py: from .hass_client import HASS_URL, HASS_TOKEN`
- `src/trmnl_server/components.py: from .models import CalendarEvent, DashboardConfig, RenderData`
- `src/trmnl_server/config.py: from .models import Config, DashboardConfig, DeviceConfig, ScheduleEntry`
- `src/trmnl_server/hass_client.py: from .models import EntityState, HistoryPoint, CalendarEvent`
- `src/trmnl_server/server.py: from .api import APICalls`

Confirm no flat internal imports remain:
Run: `grep -rnE "^from (models|state|components|config|hass_client|api) import" src/trmnl_server/`
Expected: no output.

- [ ] **Step 5: Add the `Path` import to components.py**

In `src/trmnl_server/components.py`, after the line `from math import ceil, sqrt` add:

```python
from pathlib import Path
```

Resulting stdlib import block:

```python
from datetime import datetime, timedelta
from io import BytesIO
from math import ceil, sqrt
from pathlib import Path
from typing import TYPE_CHECKING
```

- [ ] **Step 6: Point the font constant at the bundled asset**

In `src/trmnl_server/components.py`, replace:

```python
NOTO_FONT: str = "NotoSans-Regular.ttf"
```

with:

```python
NOTO_FONT: str = str(Path(__file__).parent / "assets" / "NotoSans-Regular.ttf")
```

- [ ] **Step 7: Repoint test imports to the package**

```bash
sed -i -E "s/^from (api|components|config|hass_client|models|server|state) import/from trmnl_server.\1 import/" tests/*.py
sed -i -E "s/^import (api|components|config|hass_client|models|server|state)[[:space:]]*$/from trmnl_server import \1/" tests/*.py
```

(The first line handles `from api import APICalls`-style imports, including the multi-line `from components import (`. The second handles `import api` in `test_api.py`, becoming `from trmnl_server import api` so `api.read_config` references still resolve.)

- [ ] **Step 8: Repoint test patch targets to the package**

```bash
sed -i -E "s/patch\('(api|components|config|hass_client|models|server|state)\./patch('trmnl_server.\1./g" tests/*.py
```

This rewrites every `mock.patch('<module>.…')` (e.g. `'config.read_config'`, `'components.ImageFont.truetype'`, `'server.makedirs'`, `'hass_client.get_entity_state'`, `'state.server_state'`) to its `trmnl_server.<module>.…` equivalent.

Verify no stale flat patch targets remain:
Run: `grep -rnE "patch\('(api|components|config|hass_client|models|server|state)\." tests/`
Expected: no output.

- [ ] **Step 9: Configure pytest to find the package**

Append to `pyproject.toml`:

```toml
[tool.pytest.ini_options]
pythonpath = ["src"]
```

- [ ] **Step 10: Run the full suite — must match baseline**

Run: `uv run --with pytest --with pyyaml pytest -q`
Expected: `116 passed`. If anything fails, fix the import/patch path it names (it will be a string the sed missed) before committing. Do NOT commit on a red suite.

- [ ] **Step 11: Smoke-check both launch forms import cleanly**

Run: `PYTHONPATH=src uv run --with pyyaml python -c "import trmnl_server.server, trmnl_server.__main__; print('imports ok')"`
Expected: `imports ok` (no ImportError).

- [ ] **Step 12: Commit**

```bash
git add -A
git commit -m "refactor: Move code into src/trmnl_server package

Move the flat top-level modules into a src/ package, bundle the font
inside the package, relocate tests to tests/, and switch intra-package
imports to relative. Behavior-preserving: 116 tests still pass.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Add the font-resolves regression test

The font loader falls back to `ImageFont.load_default()` on `IOError`, and `test_golden.py` auto-generates its baselines from whatever renders — so a broken font path would pass silently. This test makes a broken path a hard failure.

**Files:**
- Create: `tests/test_font_asset.py`

- [ ] **Step 1: Write the test**

Create `tests/test_font_asset.py`:

```python
"""Regression test: the bundled font must resolve to a real, loadable file.

Without this, a wrong NOTO_FONT path would be masked by the IOError ->
load_default() fallback in components._load_font, and the golden tests
(which generate baselines from whatever renders) would not catch it.
"""
import os
import unittest

from PIL import ImageFont

from trmnl_server.components import NOTO_FONT


class TestFontAsset(unittest.TestCase):
    def test_font_path_points_at_existing_file(self):
        self.assertTrue(
            os.path.isfile(NOTO_FONT),
            f"Bundled font not found at {NOTO_FONT}",
        )

    def test_font_loads_without_fallback(self):
        # Must not raise IOError (which would trigger the load_default fallback).
        font = ImageFont.truetype(NOTO_FONT, 20)
        self.assertIsInstance(font, ImageFont.FreeTypeFont)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the new test — expect PASS (the path is already correct)**

Run: `uv run --with pytest --with pyyaml pytest tests/test_font_asset.py -v`
Expected: 2 passed.

- [ ] **Step 3: Prove it actually catches a broken path**

Temporarily break the path to confirm the guard works, then restore it:

```bash
sed -i 's#"assets" / "NotoSans-Regular.ttf"#"assets" / "DOES-NOT-EXIST.ttf"#' src/trmnl_server/components.py
uv run --with pytest --with pyyaml pytest tests/test_font_asset.py -q ; echo "exit=$?"
git checkout src/trmnl_server/components.py
```
Expected: the run FAILS (both tests red, `exit=1`), then `git checkout` restores the correct path.

- [ ] **Step 4: Re-run the full suite**

Run: `uv run --with pytest --with pyyaml pytest -q`
Expected: `118 passed` (116 + 2 new).

- [ ] **Step 5: Commit**

```bash
git add tests/test_font_asset.py
git commit -m "test: Assert bundled font resolves to a loadable file

Guards against the font path silently falling back to the default font.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Update Docker build and runtime

**Files:**
- Modify: `Dockerfile`
- Modify: `entrypoint.sh`
- Modify: `.dockerignore`

- [ ] **Step 1: Update the Dockerfile copy + add PYTHONPATH**

In `Dockerfile`, replace:

```dockerfile
COPY *.py NotoSans-Regular.ttf ./
```

with:

```dockerfile
COPY src/ ./src/
ENV PYTHONPATH=/app/src
```

(The font now ships inside `src/trmnl_server/assets/`, so it no longer needs a separate `COPY`. `WORKDIR /app` is unchanged, so the standalone `-v .../config.yaml:/app/config.yaml` mount still works.)

- [ ] **Step 2: Update entrypoint.sh launch commands**

In `entrypoint.sh`, change both invocations of the server. Replace:

```sh
    exec python3 server.py --port "${PORT:-8000}"
```
with:
```sh
    exec python3 -m trmnl_server.server --port "${PORT:-8000}"
```

and replace:

```sh
    exec python3 server.py "$@"
```
with:
```sh
    exec python3 -m trmnl_server.server "$@"
```

- [ ] **Step 3: Update .dockerignore for the new test location**

In `.dockerignore`, replace the line:

```
test_*.py
```
with:
```
tests/
```

- [ ] **Step 4: Verify the image builds**

Run: `docker build -t trmnl-server-restructure-check .`
Expected: build succeeds (BuildKit `naming to ... done`), no `COPY` errors.

- [ ] **Step 5: Smoke-boot the server inside the image**

Run:
```bash
docker run --rm -e PORT=8000 trmnl-server-restructure-check \
  python3 -c "import trmnl_server.server; print('module import ok in image')"
```
Expected: `module import ok in image`.

- [ ] **Step 6: Clean up the throwaway image**

Run: `docker image rm trmnl-server-restructure-check`
Expected: image removed.

- [ ] **Step 7: Commit**

```bash
git add Dockerfile entrypoint.sh .dockerignore
git commit -m "build: Run server as trmnl_server package module in Docker

Copy src/ with PYTHONPATH=/app/src and launch via
python -m trmnl_server.server. Ignore tests/ instead of test_*.py.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Move sample files to examples/ and update docs

**Files:**
- Move: `config.yaml`, `deployment.yaml` → `examples/`
- Modify: `.dockerignore`
- Modify: `README.md`
- Modify: `AGENTS.md`

- [ ] **Step 1: Move the sample files**

```bash
mkdir -p examples
git mv config.yaml examples/config.yaml
git mv deployment.yaml examples/deployment.yaml
```

- [ ] **Step 2: Update .dockerignore sample paths**

In `.dockerignore`, replace:

```
# User config — mounted as a volume at runtime
config.yaml
```
with:
```
# User config — mounted as a volume at runtime
examples/config.yaml
```

and replace:

```
deployment.yaml
```
with:
```
examples/deployment.yaml
```

- [ ] **Step 3: Update README run + sample references**

In `README.md`:

- Replace the local-run command `python3 server.py` with:
  ```
  PYTHONPATH=src python3 -m trmnl_server.server
  ```
- The Docker `-v "$(pwd)/config.yaml:/app/config.yaml"` example: change the host side to the new location:
  ```
  docker run -p 8000:8000 --env-file .env -v "$(pwd)/examples/config.yaml:/app/config.yaml" trmnl-ha-server
  ```
- Anywhere the docs tell the reader to copy/edit the sample config, point them at `examples/config.yaml`. The runtime default (`CONFIG_PATH` defaulting to `config.yaml`) is unchanged — only the sample's repo location moved.

- [ ] **Step 4: Update AGENTS.md run command, test commands, and structure tree**

In `AGENTS.md`:

- Replace `python3 server.py` with `PYTHONPATH=src python3 -m trmnl_server.server`.
- Replace the test commands to reflect the new paths and runner:
  ```
  uv run --with pytest --with pyyaml pytest tests/test_config.py tests/test_api.py -v
  ```
  and the single-test example:
  ```
  uv run --with pytest --with pyyaml pytest tests/test_api.py::TestAPISimple::test_api_setup -v
  ```
- Replace the `## Project Structure` tree with the new layout:
  ```
  ├── src/trmnl_server/
  │   ├── server.py        # Entry point - sets up logging and starts server
  │   ├── api.py           # HTTP request handlers (APICalls class)
  │   ├── components.py    # Image rendering functions for all component types
  │   ├── hass_client.py   # Home Assistant API client
  │   ├── config.py        # Configuration loading and validation
  │   ├── state.py         # Server state management
  │   ├── models.py        # Type definitions (TypedDict, Protocol)
  │   └── assets/NotoSans-Regular.ttf
  ├── tests/               # Unit/integration tests (test_<module>.py)
  ├── examples/
  │   ├── config.yaml      # Sample dashboard configuration
  │   └── deployment.yaml  # Kubernetes deployment manifest
  ├── pyproject.toml       # Project metadata, dependencies, pytest config
  ├── requirements.txt     # Runtime dependencies
  └── Dockerfile           # Multi-stage container build
  ```

- [ ] **Step 5: Verify the suite still passes from the moved sample location**

Run: `uv run --with pytest --with pyyaml pytest -q`
Expected: `118 passed`. (Tests build their own config fixtures and do not read the repo-root `config.yaml`, so the move must not affect them — this run confirms it.)

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "docs: Move sample config/deployment to examples and update docs

Relocate config.yaml and deployment.yaml under examples/, and update
README, AGENTS.md, and .dockerignore for the new package layout and
run command.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Final Verification (whole-plan acceptance)

- [ ] **Full suite green:** `uv run --with pytest --with pyyaml pytest -q` → `118 passed` (116 baseline + 2 font tests).
- [ ] **No stale flat references:** `grep -rnE "patch\('(api|components|config|hass_client|models|server|state)\.|^from (api|components|config|hass_client|models|server|state) import" tests/ src/` → no output.
- [ ] **Launch works:** `PYTHONPATH=src python3 -m trmnl_server.server --help` (or boots and binds, then Ctrl-C) → no ImportError.
- [ ] **Docker builds:** `docker build -t trmnl-server .` → succeeds.
- [ ] **Tree is clean:** only the intended files moved; `git status` clean after the final commit.
- [ ] **Acceptance:** before/after suite results identical and green — this was a pure restructure, so any behavior difference is a bug to fix before finishing.

---

## Notes / Out of Scope

- No behavior, API, or rendering changes.
- No dependency changes — the existing `pyproject.toml` (`pillow`) vs `requirements.txt` (`Pillow`, `PyYAML`) split is left as-is. pytest/PyYAML are supplied via `uv run --with` for tests.
- No console-script entry point (the chosen launch is `python -m`).
- No changes to `addon/` (references a prebuilt image) or CI workflows (build context stays `.`).
