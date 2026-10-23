# One image for the three Python services (gateway, rural-finance, project-impact) and the migrate/seed job.
# Each service selects its module with the container command. Non-root, no build tools in the final stage.
FROM python:3.12.8-slim-bookworm AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /src
COPY pyproject.toml ./
COPY packages ./packages
COPY integrations ./integrations
COPY apps/api-gateway ./apps/api-gateway
COPY apps/rural-finance ./apps/rural-finance
COPY apps/project-impact ./apps/project-impact
RUN python -m venv /opt/venv && /opt/venv/bin/pip install --upgrade pip && /opt/venv/bin/pip install .

FROM python:3.12.8-slim-bookworm AS runtime
ARG COMMIT_SHA=uncommitted
ARG BUILD_VERSION=0.1.0-local
LABEL org.opencontainers.image.title="ifad-rural-ai-platform" \
      org.opencontainers.image.description="Independent IFAD-themed demonstration platform (synthetic data)" \
      org.opencontainers.image.revision="${COMMIT_SHA}" org.opencontainers.image.version="${BUILD_VERSION}"
ENV PATH=/opt/venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 COMMIT_SHA=${COMMIT_SHA} BUILD_VERSION=${BUILD_VERSION}
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin app && mkdir -p /data/object-store && chown 10001 /data/object-store
COPY --from=build /opt/venv /opt/venv
WORKDIR /app
COPY --chown=10001 database ./database
COPY --chown=10001 scripts/seed_demo.py ./scripts/seed_demo.py
USER 10001
EXPOSE 8400 8401 8402
CMD ["uvicorn", "api_gateway.main:app", "--host", "0.0.0.0", "--port", "8400"]
