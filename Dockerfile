FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY resilient_automation_test_stand ./resilient_automation_test_stand
RUN pip install --no-cache-dir .

EXPOSE 8080

CMD ["automation-test-stand", "--host", "0.0.0.0", "--port", "8080"]
