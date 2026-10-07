FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    BGUTIL_SCRIPT_PATH=/opt/bgutil-ytdlp-pot-provider/server/build/generate_once.js

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg git curl ca-certificates nodejs npm \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

# bgutil PO Token 생성 스크립트 빌드
RUN git clone --depth 1 https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git /opt/bgutil-ytdlp-pot-provider \
    && cd /opt/bgutil-ytdlp-pot-provider/server \
    && npm ci \
    && npx tsc

COPY main.py /app/main.py

CMD ["python", "main.py"]
