ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN groupadd --system cbom && useradd --system --gid cbom --create-home cbom

RUN apt-get update \
    && apt-get install --no-install-recommends -y postgresql-client ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY db ./db
COPY src ./src
RUN pip install --no-cache-dir .

USER cbom
EXPOSE 8000
CMD ["uvicorn", "cbom_catalog.api:app", "--host", "0.0.0.0", "--port", "8000"]
