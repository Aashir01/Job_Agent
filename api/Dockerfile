# One 256MB Fly machine runs the whole pipeline (§3), so the image stays thin:
# no torch, no local model weights, no build toolchain in the final layer.
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8080
# One worker: the batch is IO-bound and a second worker would double the
# memory for no throughput on a shared-cpu-1x machine.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
