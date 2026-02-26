FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y curl poppler-utils && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV PORT=8080
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=30s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:$PORT/health || exit 1
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port $PORT --timeout-keep-alive 120"]
