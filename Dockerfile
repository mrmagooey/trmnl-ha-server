# Stage 1: Build the runtime virtual environment with uv
FROM python:3.12-slim AS builder

# uv binary for fast, lockfile-based dependency installs
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_PREFERENCE=only-system \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /app

# Install only runtime dependencies (no dev group, no project itself) from the
# lockfile. Copying just the manifests keeps this layer cached across source
# changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project


# Stage 2: Final image
FROM python:3.12-slim

ARG VERSION=dev
ENV VERSION=${VERSION}

RUN apt-get update && \
    apt-get install -y --no-install-recommends fonts-noto-core && \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

COPY src/ ./src/
ENV PYTHONPATH=/app/src
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

RUN mkdir /logs

EXPOSE 8000

LABEL io.hass.type="addon"

CMD ["/entrypoint.sh"]
