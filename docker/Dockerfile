# syntax=docker/dockerfile:1.7

# ============================================================================
# Build arguments — defaults align with docker-spec.md §3 (CUDA 12.8 matrix).
# ============================================================================
ARG CUDA_VERSION=12.8.0
ARG UBUNTU_VERSION=22.04
# cu128 wheels start at torch 2.7.0 (download.pytorch.org/whl/cu128 has no
# 2.6.x; spec matrix groups 2.6–2.9 under cu128 but the 2.6 row actually
# belongs to cu124). LuxTTS upstream does not pin a torch version.
ARG TORCH_VERSION=2.7.1
ARG TORCH_CUDA_TAG=cu128

# ============================================================================
# Builder: python venv with torch, LuxTTS runtime deps, and the API layer.
# ============================================================================
FROM nvidia/cuda:${CUDA_VERSION}-cudnn-runtime-ubuntu${UBUNTU_VERSION} AS builder

ARG TORCH_VERSION
ARG TORCH_CUDA_TAG

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.10 \
        python3.10-venv \
        python3.10-dev \
        python3-pip \
        build-essential \
        git \
        ca-certificates \
    && ln -sf /usr/bin/python3.10 /usr/local/bin/python \
    && ln -sf /usr/bin/python3.10 /usr/local/bin/python3 \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
RUN pip install --upgrade pip

# PyTorch — matched to the CUDA_VERSION ARG. LuxTTS upstream requirements.txt
# does not pin a torch version, so this stack is free to move with the spec.
RUN pip install --index-url https://download.pytorch.org/whl/${TORCH_CUDA_TAG} \
        torch==${TORCH_VERSION} torchaudio==${TORCH_VERSION}

# API-layer dependencies (FastAPI / Pydantic / SoundFile / PyAV / YAML).
COPY docker/requirements.api.txt /tmp/requirements.api.txt
RUN pip install -r /tmp/requirements.api.txt

# LuxTTS engine runtime dependencies.
#
# piper_phonemize ships wheels only via the icefall find-links mirror, hence
# the extra index. LinaCodec is a GitHub-only package so it stays in the
# requirements file (not a wheel target).
#
# The upstream ``engine/pyproject.toml`` uses the ``uv_build`` backend, which
# pip cannot consume — so we do NOT ``pip install /build/engine``. Instead we
# expose the ``zipvoice`` package through PYTHONPATH at runtime (see the
# runtime stage below).
COPY docker/requirements.engine.txt /tmp/requirements.engine.txt
RUN pip install \
        --find-links https://k2-fsa.github.io/icefall/piper_phonemize.html \
        -r /tmp/requirements.engine.txt

# Strip bytecode caches left behind by builds.
RUN find /opt/venv -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true

# ============================================================================
# Runtime: minimal image carrying only the venv + LuxTTS source + app/.
# ============================================================================
FROM nvidia/cuda:${CUDA_VERSION}-cudnn-runtime-ubuntu${UBUNTU_VERSION}

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    HF_HOME=/root/.cache/huggingface \
    HF_HUB_ENABLE_HF_TRANSFER=1 \
    PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/opt/api:/opt/api/engine

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.10 \
        ffmpeg \
        libsndfile1 \
        ca-certificates \
    && ln -sf /usr/bin/python3.10 /usr/local/bin/python \
    && ln -sf /usr/bin/python3.10 /usr/local/bin/python3 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv

WORKDIR /opt/api

# Engine submodule exposed via PYTHONPATH; see note in builder stage.
COPY engine /opt/api/engine
COPY app /opt/api/app
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

VOLUME ["/voices", "/root/.cache"]
EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "8000"]
