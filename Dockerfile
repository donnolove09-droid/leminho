FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY index.py .
COPY index.html .

ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
ENV PYTHONUNBUFFERED=1
ENV PORT=10000
ENV MAX_CONCURRENT=2
ENV HARD_TIMEOUT=60

EXPOSE 10000

CMD ["sh", "-c", "uvicorn index:app --host 0.0.0.0 --port ${PORT}"]
