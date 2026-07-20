# Use the official lightweight Python 3.12 slim image
FROM python:3.12-slim

# Prevent Python from writing .pyc files and enable immediate logging/stdout buffering
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set the default port for Google Cloud Run
ENV PORT=8080

# Create and set working directory
WORKDIR /app

# Install system dependencies if required (pure-python PyMySQL does not need C clients)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system appuser \
    && useradd --system --gid appuser --create-home appuser

# Copy requirements file first to leverage Docker layer caching
COPY requirements.txt .

# Install dependencies and production web server (gunicorn)
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt gunicorn

# Copy the rest of the application code
COPY --chown=appuser:appuser . .

# Create directory for uploads if they do not exist
RUN mkdir -p uploads static/images/student_photos \
    && chown -R appuser:appuser /app

# Expose port 8080
EXPOSE 8080

# Run the application as an unprivileged user.
USER appuser

# Run the Flask app using Gunicorn.
# Using 4 workers, 2 threads, and a timeout of 120 seconds to handle request concurrency.
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT:-8080} --workers 4 --threads 2 --timeout 120 app:app"]
