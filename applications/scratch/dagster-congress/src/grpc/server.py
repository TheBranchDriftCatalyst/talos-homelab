"""
gRPC Server

Runs the Knowledge Graph MCP service.
"""

import os
import signal
import sys
from concurrent import futures

import grpc
import structlog
from prometheus_client import start_http_server, Counter, Histogram

from .handlers import KnowledgeGraphServicer

logger = structlog.get_logger()

# Metrics
REQUEST_COUNT = Counter(
    "grpc_requests_total",
    "Total gRPC requests",
    ["method", "status"],
)
REQUEST_LATENCY = Histogram(
    "grpc_request_latency_seconds",
    "gRPC request latency",
    ["method"],
)


class MetricsInterceptor(grpc.ServerInterceptor):
    """Interceptor for collecting Prometheus metrics."""

    def intercept_service(self, continuation, handler_call_details):
        method = handler_call_details.method.split("/")[-1]

        def wrapper(request, context):
            with REQUEST_LATENCY.labels(method=method).time():
                try:
                    response = continuation(handler_call_details).unary_unary(request, context)
                    REQUEST_COUNT.labels(method=method, status="ok").inc()
                    return response
                except Exception as e:
                    REQUEST_COUNT.labels(method=method, status="error").inc()
                    raise

        return grpc.unary_unary_rpc_method_handler(wrapper)


def serve():
    """Start the gRPC server."""
    # Import generated stubs
    try:
        from grpc.generated import knowledge_graph_pb2_grpc as pb2_grpc
    except ImportError:
        logger.error("Proto stubs not generated. Run: python -m grpc_tools.protoc ...")
        sys.exit(1)

    port = int(os.environ.get("GRPC_PORT", "50051"))
    metrics_port = int(os.environ.get("METRICS_PORT", "9091"))

    # Start Prometheus metrics server
    start_http_server(metrics_port)
    logger.info("metrics_server_started", port=metrics_port)

    # Create gRPC server
    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=10),
        interceptors=[MetricsInterceptor()],
    )

    # Add service
    servicer = KnowledgeGraphServicer()
    pb2_grpc.add_KnowledgeGraphServicer_to_server(servicer, server)

    # Enable reflection for debugging
    try:
        from grpc_reflection.v1alpha import reflection
        from grpc.generated import knowledge_graph_pb2 as pb2

        SERVICE_NAMES = (
            pb2.DESCRIPTOR.services_by_name["KnowledgeGraph"].full_name,
            reflection.SERVICE_NAME,
        )
        reflection.enable_server_reflection(SERVICE_NAMES, server)
        logger.info("grpc_reflection_enabled")
    except ImportError:
        logger.warning("grpc_reflection_not_available")

    # Bind to port
    server.add_insecure_port(f"[::]:{port}")
    server.start()
    logger.info("grpc_server_started", port=port)

    # Handle shutdown
    def shutdown(signum, frame):
        logger.info("shutdown_signal_received")
        servicer.close()
        server.stop(grace=5)
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    # Wait for termination
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
