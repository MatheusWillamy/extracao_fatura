FROM python:3.12-slim

# Prevent Python from writing .pyc files and enable immediate log streaming
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

WORKDIR /app

# Install dependencies first for Docker layer caching
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY extractor.py /app/extractor.py
COPY main.py /app/main.py

# Expose API port
EXPOSE 8000

# Healthcheck for container managers like Easypanel / Docker swarm
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Start the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
