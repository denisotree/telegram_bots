FROM python:3.9.16-slim

# Install dependencies

ARG ROOT_DIR=/telegram-bots
ARG RUNTIME_DEPENDENCIES="ffmpeg"

WORKDIR ${ROOT_DIR}

COPY requirements.txt ${ROOT_DIR}/requirements.txt

RUN apt-get update \
    && apt-get install -y $RUNTIME_DEPENDENCIES

RUN pip install -r ${ROOT_DIR}/requirements.txt

# Copy source code

COPY . ${ROOT_DIR}
