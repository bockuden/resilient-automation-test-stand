FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir ".[dev]"

COPY tests ./tests

EXPOSE 8080

CMD ["automation-test-stand", "--host", "0.0.0.0", "--port", "8080"]

