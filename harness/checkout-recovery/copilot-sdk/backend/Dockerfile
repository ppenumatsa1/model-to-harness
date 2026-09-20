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
COPY harness/checkout-recovery/copilot-sdk/pyproject.toml harness/checkout-recovery/copilot-sdk/README.md ./harness/checkout-recovery/copilot-sdk/
COPY harness/checkout-recovery/copilot-sdk/requirements-cloud*.lock ./harness/checkout-recovery/copilot-sdk/
COPY harness/checkout-recovery/copilot-sdk/scripts/verify_release_dependencies.py /build/verify_release_dependencies.py
RUN python /build/verify_release_dependencies.py --lock /build/harness/checkout-recovery/copilot-sdk/requirements-cloud.lock
COPY harness/checkout-recovery/copilot-sdk/backend/src ./harness/checkout-recovery/copilot-sdk/backend/src
COPY harness/checkout-recovery/copilot-sdk/scripts/verify_native_runtime.py /build/verify_native_runtime.py
RUN mkdir -p "$TMPDIR" \
    && uv --no-config venv --python /usr/local/bin/python /opt/build-venv \
    && uv --no-config venv --python /usr/local/bin/python /opt/venv \
    && cd harness/checkout-recovery/copilot-sdk \
    && uv --no-config pip install --python /opt/build-venv/bin/python --default-index https://pypi.org/simple --require-hashes -r requirements-cloud-dev.lock \
    && uv --no-config build --python /opt/build-venv/bin/python --no-sources --no-build-isolation --wheel --out-dir /build/wheels /build/shared \
    && uv --no-config build --python /opt/build-venv/bin/python --no-sources --no-build-isolation --wheel --out-dir /build/wheels . \
    && uv --no-config pip install --python /opt/venv/bin/python --default-index https://pypi.org/simple --require-hashes -r requirements-cloud.lock \
    && uv --no-config pip install --python /opt/venv/bin/python --no-deps /build/wheels/*.whl \
    && /opt/venv/bin/python /build/verify_release_dependencies.py --lock requirements-cloud.lock --installed \
    && cd / \
    && /opt/venv/bin/python -c "from checkout_recovery_copilot.main import create_app; from importlib.metadata import distribution; import json; assert all(not json.loads(distribution(name).read_text('direct_url.json')).get('dir_info', {}).get('editable', False) for name in ('checkout-recovery-copilot', 'model-to-harness-shared'))" \
    && COPILOT_CLI_EXTRACT_DIR=/opt/copilot-runtime /opt/venv/bin/python -m copilot download-runtime --version 1.0.85 \
    && /opt/venv/bin/python /build/verify_native_runtime.py --binary /opt/copilot-runtime/prebuilds/linux-x64/copilot-runtime --state-root /build/.scratch \
    && chmod -R a+rX /opt/copilot-runtime

FROM python:3.13-slim
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CHECKOUT_COPILOT_STATE_DIRECTORY=/home/checkout/copilot-state \
    COPILOT_CLI_EXTRACT_DIR=/opt/copilot-runtime \
    COPILOT_SKIP_CLI_DOWNLOAD=true
RUN groupadd --gid 10001 checkout \
    && useradd --uid 10001 --gid checkout --create-home checkout
COPY --from=build /opt/venv /opt/venv
COPY --from=build /opt/copilot-runtime /opt/copilot-runtime
COPY --from=build /build/verify_native_runtime.py /opt/verify_native_runtime.py
WORKDIR /app
COPY harness/checkout-recovery/copilot-sdk/backend/migrations ./migrations
USER checkout
EXPOSE 8030
CMD ["uvicorn", "checkout_recovery_copilot.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8030"]
