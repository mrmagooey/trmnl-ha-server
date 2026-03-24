# Stage 1: Build virtual environment
FROM python:3.12-slim AS builder

RUN pip install uv

RUN uv venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN uv pip install --no-cache-dir -r requirements.txt


# Stage 2: Final image
FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends fonts-noto-core && \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

COPY *.py NotoSans-Regular.ttf ./

RUN mkdir /logs

EXPOSE 8000

CMD ["python", "server.py"]
