FROM python:3.13-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.11.2 /uv /usr/local/bin/uv
ENV UV_NO_CACHE=1 \
    UV_NO_PROGRESS=1 \
    UV_PYTHON_DOWNLOADS=never \
    TMPDIR=/build/.scratch \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /build
COPY LICENSE ./LICENSE
COPY shared/pyproject.toml shared/README.md ./shared/
COPY shared/src ./shared/src
COPY harness/checkout-recovery/maf/pyproject.toml harness/checkout-recovery/maf/README.md ./harness/checkout-recovery/maf/
COPY harness/checkout-recovery/maf/backend/src ./harness/checkout-recovery/maf/backend/src
ARG UV_DEFAULT_INDEX=https://pypi.org/simple
RUN mkdir -p "$TMPDIR" \
    && uv venv --python /usr/local/bin/python /opt/venv \
    && uv pip install --no-sources --python /opt/venv/bin/python ./shared ./harness/checkout-recovery/maf

FROM python:3.13-slim
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
RUN groupadd --gid 10001 checkout \
    && useradd --uid 10001 --gid checkout --create-home checkout
COPY --from=build /opt/venv /opt/venv
WORKDIR /app
COPY harness/checkout-recovery/maf/backend/migrations ./migrations
USER checkout
EXPOSE 8000
CMD ["uvicorn", "checkout_recovery_maf.bootstrap:app", "--host", "0.0.0.0", "--port", "8000"]
