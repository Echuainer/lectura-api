FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    HF_HOME=/models HF_HUB_OFFLINE=0 OMP_NUM_THREADS=4
WORKDIR /app

# torch CPU wheel (~200 MB instead of ~2 GB with CUDA)
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu
COPY requirements.txt requirements-api.txt ./
RUN pip install -r requirements.txt

COPY core ./core
COPY config ./config
COPY scripts ./scripts
# Build with --build-arg WITH_WHISPER=1 to also bake the optional Whisper engine (+~0.8 GB)
ARG WITH_WHISPER=0
RUN python scripts/download_models.py $( [ "$WITH_WHISPER" = "1" ] && echo --whisper )
ENV HF_HUB_OFFLINE=1

COPY app ./app
COPY migrations ./migrations

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://localhost:{os.environ.get(\"PORT\",\"8000\")}/actuator/health')"
# A single process: the worker thread and the models (~2 GB) live in it. Do not add --workers.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
