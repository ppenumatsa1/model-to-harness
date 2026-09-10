FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.11.2 /uv /usr/local/bin/uv

WORKDIR /workspace/agent-framework/double-charge/maf
COPY LICENSE /workspace/LICENSE
COPY shared/pyproject.toml shared/README.md /workspace/shared/
COPY shared/src /workspace/shared/src
COPY agent-framework/double-charge/maf/pyproject.toml agent-framework/double-charge/maf/uv.lock agent-framework/double-charge/maf/README.md ./
COPY agent-framework/double-charge/maf/backend/src ./backend/src
COPY agent-framework/double-charge/maf/backend/migrations ./backend/migrations
RUN mkdir -p .build-cache \
    && TMPDIR=/workspace/agent-framework/double-charge/maf/.build-cache \
       uv sync --frozen --no-dev --no-editable --no-python-downloads --no-cache \
    && rm -rf .build-cache

FROM python:3.12-slim
WORKDIR /workspace/agent-framework/double-charge/maf
COPY --from=build /workspace/agent-framework/double-charge/maf/.venv ./.venv
ENV PATH="/workspace/agent-framework/double-charge/maf/.venv/bin:${PATH}"
ENV HOST=0.0.0.0 PORT=8010 APP_ENV=production
EXPOSE 8010
CMD ["uvicorn", "maf_double_charge.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8010"]
