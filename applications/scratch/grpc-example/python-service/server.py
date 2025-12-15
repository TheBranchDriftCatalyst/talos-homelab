#!/usr/bin/env python3
"""
Python gRPC Echo Server with Prometheus metrics and OpenTelemetry tracing.

Demonstrates:
- Unary and streaming gRPC calls
- Prometheus metrics exposition
- OpenTelemetry distributed tracing
- Cross-service communication with Go service
"""

import logging
import os
import sys
import time
import threading
from concurrent import futures

import grpc
from grpc_interceptor import ServerInterceptor
from prometheus_client import Counter, Histogram, start_http_server

# OpenTelemetry
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource, SERVICE_NAME, SERVICE_VERSION
from opentelemetry.instrumentation.grpc import GrpcInstrumentorClient, GrpcInstrumentorServer

# Add generated code to path
sys.path.insert(0, os.path.dirname(__file__))
from gen import echo_pb2, echo_pb2_grpc

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Prometheus metrics
GRPC_REQUESTS = Counter(
    'grpc_server_requests_total',
    'Total gRPC requests',
    ['method', 'service']
)
GRPC_LATENCY = Histogram(
    'grpc_server_latency_seconds',
    'gRPC request latency',
    ['method', 'service'],
    buckets=[.005, .01, .025, .05, .1, .25, .5, 1, 2.5, 5, 10]
)
GRPC_CLIENT_REQUESTS = Counter(
    'grpc_client_requests_total',
    'Total outgoing gRPC requests',
    ['method', 'target']
)


def init_tracer(service_name: str):
    """Initialize OpenTelemetry tracer with OTLP exporter."""
    otlp_endpoint = os.getenv('OTEL_EXPORTER_OTLP_ENDPOINT', 'localhost:4317')

    resource = Resource.create({
        SERVICE_NAME: service_name,
        SERVICE_VERSION: "1.0.0",
    })

    provider = TracerProvider(resource=resource)

    try:
        exporter = OTLPSpanExporter(
            endpoint=otlp_endpoint,
            insecure=True,
        )
        processor = BatchSpanProcessor(exporter)
        provider.add_span_processor(processor)
        trace.set_tracer_provider(provider)
        logger.info(f"OpenTelemetry tracer initialized for {service_name}, endpoint: {otlp_endpoint}")
    except Exception as e:
        logger.warning(f"Failed to initialize OTLP exporter: {e}")

    return trace.get_tracer(service_name)


class PrometheusInterceptor(ServerInterceptor):
    """gRPC interceptor for Prometheus metrics."""

    def intercept(self, method, request_or_iterator, context, method_name):
        GRPC_REQUESTS.labels(method=method_name, service='EchoService').inc()
        start = time.time()
        try:
            return method(request_or_iterator, context)
        finally:
            GRPC_LATENCY.labels(method=method_name, service='EchoService').observe(
                time.time() - start
            )


class EchoServicer(echo_pb2_grpc.EchoServiceServicer):
    """Echo service implementation."""

    def __init__(self, service_name: str, tracer):
        self.service_name = service_name
        self.tracer = tracer

    def Echo(self, request, context):
        # Get current span and add attributes
        current_span = trace.get_current_span()
        current_span.set_attribute("rpc.method", "Echo")
        current_span.set_attribute("rpc.service", "EchoService")
        current_span.set_attribute("echo.sender", request.sender)

        logger.info(f"[{self.service_name}] Received Echo from {request.sender}: {request.message}")
        return echo_pb2.EchoResponse(
            message=f"Echo: {request.message}",
            responder=self.service_name,
            timestamp=int(time.time() * 1e9)
        )

    def EchoStream(self, request_iterator, context):
        for request in request_iterator:
            logger.info(
                f"[{self.service_name}] Stream received from {request.sender}: {request.message}"
            )
            yield echo_pb2.EchoResponse(
                message=f"Stream Echo: {request.message}",
                responder=self.service_name,
                timestamp=int(time.time() * 1e9)
            )


def start_client(peer_address: str, service_name: str, tracer):
    """Background client that periodically calls the peer service."""
    time.sleep(5)  # Wait for services to start

    channel = grpc.insecure_channel(peer_address)
    stub = echo_pb2_grpc.EchoServiceStub(channel)

    counter = 0
    while True:
        counter += 1

        # Create a span for the client call
        with tracer.start_as_current_span("client.Echo", kind=trace.SpanKind.CLIENT) as span:
            span.set_attribute("rpc.method", "Echo")
            span.set_attribute("rpc.system", "grpc")
            span.set_attribute("peer.address", peer_address)

            try:
                GRPC_CLIENT_REQUESTS.labels(method='Echo', target=peer_address).inc()
                response = stub.Echo(
                    echo_pb2.EchoRequest(
                        message=f"Hello #{counter} from {service_name}",
                        sender=service_name
                    ),
                    timeout=5
                )
                logger.info(
                    f"[{service_name}] Got response from {response.responder}: {response.message}"
                )
                span.set_attribute("echo.responder", response.responder)
            except grpc.RpcError as e:
                logger.warning(f"Echo call failed: {e.code()} - {e.details()}")
                span.record_exception(e)
                span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))

        time.sleep(10)


def serve():
    grpc_port = os.getenv('GRPC_PORT', '50052')
    metrics_port = int(os.getenv('METRICS_PORT', '9091'))
    service_name = os.getenv('SERVICE_NAME', 'python-service')
    peer_address = os.getenv('PEER_ADDRESS', '')

    # Initialize OpenTelemetry
    tracer = init_tracer(service_name)

    # Instrument gRPC
    GrpcInstrumentorServer().instrument()
    GrpcInstrumentorClient().instrument()

    # Start Prometheus metrics server
    start_http_server(metrics_port)
    logger.info(f"Metrics server listening on :{metrics_port}")

    # Create gRPC server with interceptor
    interceptors = [PrometheusInterceptor()]
    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=10),
        interceptors=interceptors
    )
    echo_pb2_grpc.add_EchoServiceServicer_to_server(
        EchoServicer(service_name, tracer), server
    )

    # Enable reflection for grpcurl/debugging
    from grpc_reflection.v1alpha import reflection
    SERVICE_NAMES = (
        echo_pb2.DESCRIPTOR.services_by_name['EchoService'].full_name,
        reflection.SERVICE_NAME,
    )
    reflection.enable_server_reflection(SERVICE_NAMES, server)

    server.add_insecure_port(f'[::]:{grpc_port}')
    server.start()
    logger.info(f"gRPC server {service_name} listening on :{grpc_port}")

    # Start background client if peer is configured
    if peer_address:
        client_thread = threading.Thread(
            target=start_client,
            args=(peer_address, service_name, tracer),
            daemon=True
        )
        client_thread.start()

    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        server.stop(grace=5)


if __name__ == '__main__':
    serve()
