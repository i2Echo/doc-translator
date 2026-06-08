FROM python:3.12-alpine

ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/apps/api

WORKDIR /app

RUN apk add --no-cache \
    font-noto-cjk \
    tesseract-ocr \
    tesseract-ocr-data-eng \
    tesseract-ocr-data-chi_sim \
    tesseract-ocr-data-osd \
    py3-onnxruntime \
    py3-opencv \
    py3-scikit-learn \
    py3-scipy

RUN apk add --no-cache --virtual .build-deps \
    build-base \
    git \
    python3-dev \
    libffi-dev \
    protobuf-dev

COPY apps/api/requirements.txt /tmp/requirements.txt
COPY infra/docker/babeldoc-requirements.txt /tmp/babeldoc-requirements.txt
COPY infra/docker/patch_babeldoc.py /tmp/patch_babeldoc.py
RUN rm -rf /usr/lib/python3.12/site-packages/opencv-python-*.dist-info \
    && python -m pip install --break-system-packages --no-cache-dir -i "${PIP_INDEX_URL}" -r /tmp/requirements.txt \
    && python -m pip install --break-system-packages --no-cache-dir -i "${PIP_INDEX_URL}" -r /tmp/babeldoc-requirements.txt \
    && python -m pip install --break-system-packages --no-cache-dir --no-deps -i "${PIP_INDEX_URL}" BabelDOC==0.6.2 \
    && python /tmp/patch_babeldoc.py

COPY . /app

EXPOSE 8000 8001
