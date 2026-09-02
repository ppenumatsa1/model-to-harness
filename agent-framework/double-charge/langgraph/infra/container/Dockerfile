FROM python:3.12-slim

WORKDIR /workspace
COPY LICENSE /workspace/LICENSE
COPY shared /workspace/shared
COPY agent-framework/double-charge/langgraph /workspace/langgraph
RUN python -m pip install --no-cache-dir /workspace/shared "/workspace/langgraph[observability]"

ENV APP_ENV=production HOST=0.0.0.0 PORT=8000
EXPOSE 8000
CMD ["uvicorn", "model_to_harness_langgraph.main:app", "--host", "0.0.0.0", "--port", "8000"]
