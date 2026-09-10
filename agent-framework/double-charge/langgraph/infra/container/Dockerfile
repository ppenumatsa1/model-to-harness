FROM python:3.12-slim

ARG SOURCE_COMMIT
ARG SOURCE_SHA256
LABEL org.opencontainers.image.revision=$SOURCE_COMMIT
LABEL io.model-to-harness.source-sha256=$SOURCE_SHA256

COPY LICENSE /workspace/LICENSE
COPY shared /workspace/shared
COPY agent-framework/double-charge/langgraph /workspace/agent-framework/double-charge/langgraph
WORKDIR /workspace/agent-framework/double-charge/langgraph
RUN python -m pip install --no-cache-dir uv==0.11.2 \
    && uv sync --frozen --no-dev --extra observability --no-editable

ENV PATH="/workspace/agent-framework/double-charge/langgraph/.venv/bin:$PATH"

ENV APP_ENV=production HOST=0.0.0.0 PORT=8000
EXPOSE 8000
CMD ["uvicorn", "model_to_harness_langgraph.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
