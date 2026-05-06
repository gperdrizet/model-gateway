FROM python:3.12-slim

RUN useradd --system --no-create-home --shell /bin/false gateway

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

USER gateway

EXPOSE 8503

HEALTHCHECK --interval=10s --timeout=5s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8503/health')"

CMD ["uvicorn", "app.app:app", "--host", "0.0.0.0", "--port", "8503"]
