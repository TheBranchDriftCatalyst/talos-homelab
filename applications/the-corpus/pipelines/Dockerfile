# Corpus Pipelines - Dagster User Code
#
# Build from the-corpus root directory:
#   docker build -t corpus-pipelines -f pipelines/Dockerfile .

FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy corpus-core first (dependency)
COPY corpus-core/ /app/corpus-core/

# Copy pipelines
COPY pipelines/pyproject.toml /app/
COPY pipelines/src/ /app/src/

# Install packages
RUN pip install --no-cache-dir -e /app/corpus-core && \
    pip install --no-cache-dir -e /app

WORKDIR /app/src

# Dagster code server
EXPOSE 4000

# Health check endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import socket; s=socket.socket(); s.connect(('localhost', 4000)); s.close()" || exit 1

# Run Dagster code server
CMD ["dagster", "code-server", "start", "-h", "0.0.0.0", "-p", "4000", "-m", "definitions"]
