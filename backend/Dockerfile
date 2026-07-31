# InsightHub backend — FastAPI on Python 3.12.
FROM python:3.12-slim

WORKDIR /app

# Python deps first (better layer caching).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-install the DuckDB Postgres extension so the container works without a
# runtime download (needed when IH_DATABASE_URL points at Postgres).
RUN python -c "import duckdb; c=duckdb.connect(); c.execute('INSTALL postgres')"

COPY app ./app
COPY scripts ./scripts

# Data dir for the DuckDB file backend (unused when IH_DATABASE_URL is set).
ENV IH_DATA_DIR=/data
RUN mkdir -p /data
EXPOSE 8010

# Readiness at /api/ready (checks the DB); liveness at /api/health.
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8010/api/ready').status==200 else 1)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8010"]
