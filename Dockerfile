ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml ./
RUN python -c "import tomllib; p = tomllib.load(open('pyproject.toml', 'rb'))['project']; \
print('\n'.join(p['dependencies'] + p['optional-dependencies']['pipeline']))" \
        > /tmp/requirements.txt \
    && pip install -r /tmp/requirements.txt

COPY README.md alembic.ini ./
COPY app ./app
COPY pipeline ./pipeline
COPY migrations ./migrations
RUN pip install --no-deps .

RUN useradd --create-home --uid 1000 songly
USER songly
RUN mkdir -p /home/songly/.prefect

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
