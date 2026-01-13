# Multi-stage Dockerfile for Dagster Congress ETL Pipeline
# Stage 1: Build dependencies
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency files
COPY pyproject.toml .

# Create virtual environment and install dependencies
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

# Stage 2: Runtime
FROM python:3.11-slim

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application code
COPY . .

# Generate proto stubs (if proto files exist)
RUN if [ -d "grpc/proto" ]; then \
    python -m grpc_tools.protoc \
        -I grpc/proto \
        --python_out=grpc/generated \
        --grpc_python_out=grpc/generated \
        grpc/proto/*.proto || true; \
    fi

# Create non-root user
RUN useradd -m -u 1000 dagster && \
    chown -R dagster:dagster /app
USER dagster

# Expose Dagster gRPC port
EXPOSE 3030

# Default command for Dagster code server
CMD ["dagster", "api", "grpc", "-h", "0.0.0.0", "-p", "3030", "-f", "definitions.py"]
