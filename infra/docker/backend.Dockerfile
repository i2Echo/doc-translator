FROM python:3.12-slim-bookworm

ARG DEBIAN_MIRROR=http://mirrors.tuna.tsinghua.edu.cn/debian
ARG DEBIAN_SECURITY_MIRROR=http://mirrors.tuna.tsinghua.edu.cn/debian-security

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/apps/api

WORKDIR /app

RUN set -eux; \
    printf 'deb %s bookworm main\n' "$DEBIAN_MIRROR" > /etc/apt/sources.list; \
    printf 'deb %s bookworm-updates main\n' "$DEBIAN_MIRROR" >> /etc/apt/sources.list; \
    printf 'deb %s bookworm-security main\n' "$DEBIAN_SECURITY_MIRROR" >> /etc/apt/sources.list; \
    rm -f /etc/apt/sources.list.d/debian.sources; \
    rm -f /etc/apt/apt.conf.d/docker-clean; \
    for attempt in 1 2 3 4 5; do \
        apt-get -o Acquire::Retries=5 update; \
        if apt-get -o Acquire::Retries=5 install -y --no-install-recommends \
            fonts-noto-core \
            fonts-wqy-zenhei \
            libglib2.0-0 \
            libgl1 \
            libgomp1 \
            libreoffice-impress \
            tesseract-ocr \
            tesseract-ocr-chi-sim \
            tesseract-ocr-eng \
            tesseract-ocr-osd; \
        then \
            break; \
        fi; \
        if [ "$attempt" = "5" ]; then \
            exit 1; \
        fi; \
        sleep $((attempt * 10)); \
    done; \
    rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*.deb

COPY apps/api/requirements.txt /tmp/requirements.txt
COPY infra/docker/babeldoc-requirements.txt /tmp/babeldoc-requirements.txt
RUN python -m pip install --break-system-packages --no-cache-dir -r /tmp/requirements.txt \
    && python -m pip install --break-system-packages --no-cache-dir --only-binary=onnx,onnxruntime,opencv-python-headless,scikit-learn,scipy -r /tmp/babeldoc-requirements.txt \
    && python -m pip install --break-system-packages --no-cache-dir --only-binary=onnx,onnxruntime,opencv-python-headless,scikit-learn,scipy BabelDOC==0.6.2

COPY alembic.ini /app/alembic.ini
COPY apps/api /app/apps/api
COPY apps/worker /app/apps/worker

EXPOSE 8000 8001
