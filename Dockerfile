FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN groupadd --gid 10001 appuser \
    && useradd --uid 10001 --gid appuser --no-create-home --shell /usr/sbin/nologin appuser

COPY pyproject.toml README.md ./
COPY resilient_automation_test_stand ./resilient_automation_test_stand
RUN pip install --no-cache-dir .

USER appuser

EXPOSE 8080

CMD ["automation-test-stand", "--host", "0.0.0.0", "--port", "8080"]
