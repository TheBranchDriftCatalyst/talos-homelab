# Dockerfile for gRPC MCP Service
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY pyproject.toml .
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir . grpcio-reflection

# Stage 2: Runtime
FROM python:3.11-slim

WORKDIR /app

# Copy virtual environment
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application code
COPY . .

# Generate proto stubs
RUN mkdir -p grpc/generated && \
    python -m grpc_tools.protoc \
        -I grpc/proto \
        --python_out=grpc/generated \
        --grpc_python_out=grpc/generated \
        grpc/proto/*.proto && \
    touch grpc/generated/__init__.py

# Create non-root user
RUN useradd -m -u 1000 grpc && \
    chown -R grpc:grpc /app
USER grpc

# Expose ports
EXPOSE 50051 9091

# Run server
CMD ["python", "-m", "grpc.server"]
