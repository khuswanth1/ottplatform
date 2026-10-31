FROM python:3.12-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
COPY requirements.txt .
RUN /opt/venv/bin/pip install -r requirements.txt

FROM python:3.12-slim
# WITH_FFMPEG=1 is only for the transcode worker image (compose `transcoder`); the API image stays small.
ARG WITH_FFMPEG=0
RUN if [ "$WITH_FFMPEG" = "1" ]; then apt-get update && apt-get install -y --no-install-recommends ffmpeg     && rm -rf /var/lib/apt/lists/*; fi
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/opt/venv/bin:$PATH"
WORKDIR /srv
COPY --from=build /opt/venv /opt/venv
COPY alembic.ini .
COPY alembic ./alembic
COPY app ./app
RUN useradd --system --uid 10001 --no-create-home ott && mkdir -p /srv/media/incoming /srv/media/hls && chown -R ott /srv
USER ott
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/healthz')" || exit 1
# Migrations run as a separate step (see docker-compose `migrate` service / CI deploy job), never on every replica start.
# The app reads X-Forwarded-For itself (TRUST_PROXY, rightmost entry written by our own proxy); uvicorn's own proxy-header
# rewriting is off because with a wildcard allow-list it trusted the client-supplied, leftmost address.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${WEB_CONCURRENCY:-2} --no-proxy-headers --timeout-graceful-shutdown 20"]
