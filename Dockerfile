FROM python:3.9.16-slim

# Install dependencies

ARG ROOT_DIR=/telegram-bots

WORKDIR ${ROOT_DIR}

COPY requirements.txt ${ROOT_DIR}/requirements.txt

RUN pip install -r ${ROOT_DIR}/requirements.txt

# Copy source code

COPY . ${ROOT_DIR}

# Run the bot

CMD ["python", "$RUNFILE"]
