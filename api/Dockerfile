FROM python:3.14-slim

WORKDIR /app

# Install system dependencies if needed (kept minimal)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
  && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy source
COPY . /app

ENV PORT=8080
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Gunicorn entrypoint to load Flask app via api.wsgi:app
CMD ["gunicorn", "-b", ":8080", "wsgi:app"]
