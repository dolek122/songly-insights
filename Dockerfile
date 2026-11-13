# One image for every Python service: API, migrations, pipeline and Prefect server
# (ADR 0013). Each service in docker-compose.yml only changes the command.
ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 1. Dependencies only. Docker caches this layer until pyproject.toml changes, so editing
#    the code does not download Prefect & co. again. The list comes straight from
#    pyproject.toml (tomllib is in the standard library), so there is no second list to sync.
COPY pyproject.toml ./
RUN python -c "import tomllib; p = tomllib.load(open('pyproject.toml', 'rb'))['project']; \
print('\n'.join(p['dependencies'] + p['optional-dependencies']['pipeline']))" \
        > /tmp/requirements.txt \
    && pip install -r /tmp/requirements.txt

# 2. The application itself (--no-deps: they are installed above).
COPY README.md alembic.ini ./
COPY app ./app
COPY pipeline ./pipeline
COPY migrations ./migrations
RUN pip install --no-deps .

# Do not run as root: if the app were compromised, the attacker would not be root
# inside the container. The home directory is needed by Prefect (~/.prefect).
RUN useradd --create-home --uid 1000 songly
USER songly
# Created here, owned by songly: a Docker volume mounted on it later (Prefect's database)
# takes over this owner. Without it Docker would create the folder owned by root.
RUN mkdir -p /home/songly/.prefect

EXPOSE 8000
# One worker on purpose: Prometheus metrics live in the process memory (app/metrics.py).
# --no-access-log: the app writes its own access log as JSON, with the request id (ADR 0018).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
