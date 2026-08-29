FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/source \
    AIOPS_DATA_DIR=/app/data \
    AIOPS_EVENT_BUS=memory \
    AIOPS_TOPOLOGY=json \
    AIOPS_SAFETY_BACKEND=memory \
    AIOPS_REPAIR_EXECUTOR=dry-run

WORKDIR /app

COPY 02_Source/agent_tech_portfolio/requirements-fastapi.txt /tmp/requirements-fastapi.txt
COPY 02_Source/agent_tech_portfolio/requirements-production.txt /tmp/requirements-production.txt
RUN pip install --no-cache-dir -r /tmp/requirements-fastapi.txt -r /tmp/requirements-production.txt

COPY 02_Source/agent_tech_portfolio /app/source
COPY 04_Data /app/default_data
COPY 02_Source/agent_tech_portfolio/container_entrypoint.sh /usr/local/bin/aiops-entrypoint
RUN chmod +x /usr/local/bin/aiops-entrypoint

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app
USER appuser

ENTRYPOINT ["/usr/local/bin/aiops-entrypoint"]

EXPOSE 8000

CMD ["uvicorn", "fastapi_app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
