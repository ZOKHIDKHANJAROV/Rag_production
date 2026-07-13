FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY evaluation ./evaluation

EXPOSE 8003

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port 8003 --workers ${RAG_WORKERS:-4} --proxy-headers"]
