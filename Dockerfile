FROM python:3.15.2-slim-trixie@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928 AS dependencies

# Install into a venv without retaining pip or its vendored libraries at runtime.
RUN python -m venv --without-pip /opt/venv
COPY requirements.txt /tmp/requirements.txt
# Optional PEM trust bundle for corporate HTTPS inspection during the build.
# The secret mount is temporary and is not copied to the runtime image.
RUN --mount=type=secret,id=build_ca \
    if [ -f /run/secrets/build_ca ]; then \
        export PIP_CERT=/run/secrets/build_ca; \
    fi; \
    python -m pip --python /opt/venv/bin/python install \
    --no-cache-dir --require-hashes -r /tmp/requirements.txt

FROM python:3.15.2-slim-trixie@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# Apply available Debian security fixes, then remove unused installation tools.
RUN apt-get update \
    && apt-get upgrade --yes --no-install-recommends \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip uninstall --yes pip \
    && rm -rf /usr/local/lib/python3.15/ensurepip

WORKDIR /app

COPY --from=dependencies /opt/venv /opt/venv

# Copier l'application
COPY app/ ./app/

# Créer un utilisateur non-root
RUN useradd -r -u 1000 appuser
USER appuser

# Exposer le port
EXPOSE 8080

# Lancer l'application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
