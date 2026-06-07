# Restructure into a `src/` package — Design

**Date:** 2026-06-06
**Status:** Approved (pending spec review)

## Goal

Move the code out of the flat top-level directory into a proper Python
package under `src/`, separating application code, tests, assets, and
example/deployment files. This is a **behavior-preserving restructure** — no
runtime behavior changes; the test suite must go green-to-green.

## Decisions (locked)

- **Layout:** `src/` package layout (`src/trmnl_server/`), tests in `tests/`.
- **Launch:** `python -m trmnl_server.server` (no console-script install). Docker
  copies `src/` and sets `PYTHONPATH=/app/src`.
- **Font:** bundled inside the package at `src/trmnl_server/assets/`, resolved
  relative to `__file__` (CWD- and install-location-independent).
- **Samples:** `config.yaml` and `deployment.yaml` move to `examples/`.

## Target layout

```
src/trmnl_server/
  __init__.py
  __main__.py            # enables `python -m trmnl_server`
  api.py  components.py  config.py
  hass_client.py  models.py  server.py  state.py
  assets/NotoSans-Regular.ttf
tests/
  conftest.py            # only if needed beyond pyproject pythonpath
  test_api.py  test_components.py  test_config.py
  test_golden.py  test_hass_client.py  test_server.py
  test_server_module.py  test_state.py
  golden/                # auto-created by test_golden.py on first run
examples/
  config.yaml            # moved from repo root (sample dashboard config)
  deployment.yaml        # moved from repo root (k8s ConfigMap sample)
addon/                   # unchanged (HA addon manifest, references prebuilt image)
Dockerfile  entrypoint.sh  pyproject.toml  requirements.txt
README.md  CHANGELOG.md  AGENTS.md
```

## Code changes (behavior-preserving)

1. **Intra-package imports → relative.** In `api.py`, `components.py`,
   `config.py`, `hass_client.py`, `server.py`, rewrite flat absolute imports
   (`from models import X`, `from api import APICalls`, etc.) to relative
   (`from .models import X`, `from .api import APICalls`). Affects these
   internal modules only: api, components, config, hass_client, models, server,
   state.
2. **Font path.** In `components.py`, add `from pathlib import Path` and change
   `NOTO_FONT = "NotoSans-Regular.ttf"` to
   `NOTO_FONT = str(Path(__file__).parent / "assets" / "NotoSans-Regular.ttf")`.
3. **`__main__.py`.** Add `src/trmnl_server/__main__.py` that calls
   `server.main()` so `python -m trmnl_server` works. `server.py` keeps its
   existing `if __name__ == "__main__": main()` guard (still fires under
   `python -m trmnl_server.server`).

## Build / run changes

4. **Dockerfile.** Replace `COPY *.py NotoSans-Regular.ttf ./` with
   `COPY src/ ./src/`; add `ENV PYTHONPATH=/app/src`. The font ships inside
   `src/` so no separate font copy is needed. `WORKDIR /app` is unchanged, and
   the standalone `-v .../config.yaml:/app/config.yaml` mount still works
   because `CONFIG_PATH` defaults to the CWD-relative `config.yaml`.
5. **entrypoint.sh.** In both branches, change `python3 server.py …` to
   `python3 -m trmnl_server.server …`.
6. **.dockerignore.** `test_*.py` → `tests/`; `config.yaml` →
   `examples/config.yaml`; `deployment.yaml` → `examples/deployment.yaml`.

## Test changes

7. **Import + patch path updates** across all 8 test files:
   - `from api import …` → `from trmnl_server.api import …` (and the other
     modules likewise).
   - `mock.patch('components.ImageFont.truetype')` →
     `mock.patch('trmnl_server.components.ImageFont.truetype')` (and the
     `load_default` patch in `test_components.py`).
   - `test_golden.py`'s `GOLDEN_DIR = Path(__file__).parent / "golden"` needs no
     change — it follows the test file to `tests/golden/`.
8. **pytest config.** Add to `pyproject.toml`:
   ```toml
   [tool.pytest.ini_options]
   pythonpath = ["src"]
   ```
   so tests resolve the package without an install step. Add a `conftest.py`
   only if something beyond this proves necessary.
9. **New regression test** (closes the silent-fallback gap): the font loader
   falls back to `ImageFont.load_default()` on `IOError`, and `test_golden.py`
   auto-generates baselines from whatever renders — so a broken font path would
   pass silently. Add a unit test asserting that `NOTO_FONT` points at an
   existing file **and** that `ImageFont.truetype(NOTO_FONT, 20)` succeeds
   without hitting the fallback.

## Docs

10. **README.md** and **AGENTS.md:** update the run command to
    `PYTHONPATH=src python3 -m trmnl_server.server`, and update sample-config
    references (`config.yaml`, `deployment.yaml`) to point at `examples/`.

## Verification (three levels)

- **Baseline:** run the full test suite *before* any change and record the
  pass/fail counts. Every subsequent step is measured against this baseline.
- **Unit:** updated unit tests plus the new font-resolves test pass.
- **Integration:** existing config↔components↔api tests pass.
- **E2E:** `test_server.py` (HTTP) passes; smoke-boot
  `python -m trmnl_server.server` and confirm it binds the port; `docker build .`
  succeeds.
- **Acceptance:** before/after suite results are identical and green — this is a
  pure restructure, so any new failure is a regression introduced by the move.

## Out of scope

- No behavior, API, or rendering changes.
- No dependency changes (the existing `pyproject.toml`/`requirements.txt`
  `pillow`/`PyYAML` split is left as-is).
- No console-script entry point (explicitly chose `python -m`).
- No changes to `addon/` or the CI workflows (build context stays `.`).
