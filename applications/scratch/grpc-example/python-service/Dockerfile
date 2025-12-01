# Build stage - generate proto files
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build dependencies
RUN pip install --no-cache-dir grpcio-tools

# Copy proto (from parent context)
COPY proto/ ./proto/

# Generate Python stubs with correct package imports
RUN mkdir -p gen && \
    python -m grpc_tools.protoc -I./proto \
        --python_out=./gen \
        --grpc_python_out=./gen \
        ./proto/echo.proto && \
    touch gen/__init__.py && \
    # Fix the import in grpc file to use relative import
    sed -i 's/^import echo_pb2/from . import echo_pb2/' gen/echo_pb2_grpc.py

# Runtime stage
FROM python:3.12-slim

WORKDIR /app

# Install runtime dependencies
COPY python-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy generated code and server
COPY --from=builder /app/gen ./gen
COPY python-service/server.py .

EXPOSE 50052 9091

CMD ["python", "server.py"]
