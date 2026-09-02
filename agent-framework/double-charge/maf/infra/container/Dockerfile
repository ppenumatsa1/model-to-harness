FROM python:3.12-slim

WORKDIR /workspace
COPY LICENSE /workspace/LICENSE
COPY shared /workspace/shared
COPY agent-framework/double-charge/maf /workspace/maf
RUN python -m pip install --no-cache-dir /workspace/shared /workspace/maf

ENV HOST=0.0.0.0 PORT=8010 APP_ENV=production
EXPOSE 8010
CMD ["uvicorn", "maf_double_charge.main:app", "--host", "0.0.0.0", "--port", "8010"]
