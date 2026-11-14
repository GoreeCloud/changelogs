# Development-only hosted Changelogs container. No production or Stable claim.
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN python -m pip install --no-cache-dir --no-deps .

# No daemon, credentials, database or other privileged runtime access.
USER 10001:10001
ENTRYPOINT ["goree-changelogs"]
CMD ["--help"]
