FROM python:3.12-slim-bookworm

ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/apps/api

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libglib2.0-0 \
        libgl1 \
        libgomp1 \
        tesseract-ocr \
        tesseract-ocr-chi-sim \
        tesseract-ocr-eng \
        tesseract-ocr-osd \
    && rm -rf /var/lib/apt/lists/*

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        fonts-noto-core \
        fonts-noto-cjk \
        fonts-wqy-zenhei \
    && rm -rf /var/lib/apt/lists/*

COPY apps/api/requirements.txt /tmp/requirements.txt
COPY infra/docker/babeldoc-requirements.txt /tmp/babeldoc-requirements.txt
COPY infra/docker/patch_babeldoc.py /tmp/patch_babeldoc.py
RUN python -m pip install --break-system-packages --no-cache-dir -i "${PIP_INDEX_URL}" -r /tmp/requirements.txt \
    && python -m pip install --break-system-packages --no-cache-dir --only-binary=onnx,onnxruntime,opencv-python-headless,scikit-learn,scipy -i "${PIP_INDEX_URL}" -r /tmp/babeldoc-requirements.txt \
    && python -m pip install --break-system-packages --no-cache-dir --only-binary=onnx,onnxruntime,opencv-python-headless,scikit-learn,scipy -i "${PIP_INDEX_URL}" BabelDOC==0.6.2 \
    && python /tmp/patch_babeldoc.py

COPY alembic.ini /app/alembic.ini
COPY apps/api /app/apps/api
COPY apps/worker /app/apps/worker

EXPOSE 8000 8001
