# Minimal production image for Cloud Run (FastAPI / uvicorn).
# Do not bake secrets into this image — set them on the Cloud Run service.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps commonly needed by scientific Python wheels.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

# Application code + runtime mobility/historical artifacts only.
COPY src ./src
COPY data/mobility_network ./data/mobility_network
COPY models ./models

# Cloud Run injects PORT (default 8080 locally).
ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "uvicorn src.api.app:app --host 0.0.0.0 --port ${PORT}"]
