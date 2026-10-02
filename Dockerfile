FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg ca-certificates tzdata \
 && rm -rf /var/lib/apt/lists/*
# Pin this tag to the `uv --version` used in development.
COPY --from=ghcr.io/astral-sh/uv:0.12.9 /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY config ./config
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH" \
    DATA_DIR=/data \
    WHISPER_DOWNLOAD_ROOT=/models \
    TZ=Europe/Madrid
VOLUME ["/data", "/models"]
CMD ["tohoku", "run"]
