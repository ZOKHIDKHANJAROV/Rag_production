FROM pytorch/pytorch:2.0.1-cuda11.7-cudnn8-runtime

ARG COSYVOICE_REF=main
ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1

WORKDIR /opt/CosyVoice

RUN apt-get update \
    && apt-get install -y --no-install-recommends git git-lfs g++ libsndfile1 \
    && git lfs install \
    && git clone --recursive --depth 1 --branch ${COSYVOICE_REF} https://github.com/FunAudioLLM/CosyVoice.git \
    && pip3 install -r CosyVoice/requirements.txt \
    && rm -rf /var/lib/apt/lists/*

EXPOSE 50000

CMD ["sh", "-c", "cd /opt/CosyVoice/CosyVoice/runtime/python/fastapi && python3 server.py --port 50000 --model_dir ${COSYVOICE_MODEL:-iic/CosyVoice-300M-SFT}"]
