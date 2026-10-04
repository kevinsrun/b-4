FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000 \
    HOST=0.0.0.0

COPY pyproject.toml README.md requirements.txt ./
COPY bacteriocin_lab/ ./bacteriocin_lab/

RUN pip install --no-cache-dir .[web]

EXPOSE 8000

CMD ["sh", "-c", "uvicorn bacteriocin_lab.api.app:app_from_env --host 0.0.0.0 --port ${PORT:-8000}"]
