package main

import (
	"context"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/reflection"

	grpc_prometheus "github.com/grpc-ecosystem/go-grpc-prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"

	// OpenTelemetry
	"go.opentelemetry.io/contrib/instrumentation/google.golang.org/grpc/otelgrpc"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc"
	"go.opentelemetry.io/otel/propagation"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	semconv "go.opentelemetry.io/otel/semconv/v1.26.0"
	"go.opentelemetry.io/otel/trace"

	pb "grpc-example/gen/echopb"
)

const (
	defaultGRPCPort    = "50051"
	defaultMetricsPort = "9090"
)

var tracer trace.Tracer

type echoServer struct {
	pb.UnimplementedEchoServiceServer
	serviceName string
}

func (s *echoServer) Echo(ctx context.Context, req *pb.EchoRequest) (*pb.EchoResponse, error) {
	// Get current span from context
	span := trace.SpanFromContext(ctx)
	span.SetAttributes(
		semconv.RPCMethod("Echo"),
		semconv.RPCService("EchoService"),
	)

	log.Printf("[%s] Received Echo from %s: %s", s.serviceName, req.Sender, req.Message)
	return &pb.EchoResponse{
		Message:   fmt.Sprintf("Echo: %s", req.Message),
		Responder: s.serviceName,
		Timestamp: time.Now().UnixNano(),
	}, nil
}

func (s *echoServer) EchoStream(stream pb.EchoService_EchoStreamServer) error {
	for {
		req, err := stream.Recv()
		if err == io.EOF {
			return nil
		}
		if err != nil {
			return err
		}

		log.Printf("[%s] Stream received from %s: %s", s.serviceName, req.Sender, req.Message)

		resp := &pb.EchoResponse{
			Message:   fmt.Sprintf("Stream Echo: %s", req.Message),
			Responder: s.serviceName,
			Timestamp: time.Now().UnixNano(),
		}
		if err := stream.Send(resp); err != nil {
			return err
		}
	}
}

func initTracer(ctx context.Context, serviceName string) (*sdktrace.TracerProvider, error) {
	otlpEndpoint := os.Getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
	if otlpEndpoint == "" {
		otlpEndpoint = "localhost:4317"
	}

	exporter, err := otlptracegrpc.New(ctx,
		otlptracegrpc.WithEndpoint(otlpEndpoint),
		otlptracegrpc.WithInsecure(),
	)
	if err != nil {
		return nil, fmt.Errorf("failed to create OTLP exporter: %w", err)
	}

	res, err := resource.New(ctx,
		resource.WithAttributes(
			semconv.ServiceName(serviceName),
			semconv.ServiceVersion("1.0.0"),
		),
	)
	if err != nil {
		return nil, fmt.Errorf("failed to create resource: %w", err)
	}

	tp := sdktrace.NewTracerProvider(
		sdktrace.WithBatcher(exporter),
		sdktrace.WithResource(res),
		sdktrace.WithSampler(sdktrace.AlwaysSample()),
	)

	otel.SetTracerProvider(tp)
	otel.SetTextMapPropagator(propagation.NewCompositeTextMapPropagator(
		propagation.TraceContext{},
		propagation.Baggage{},
	))

	tracer = tp.Tracer(serviceName)
	return tp, nil
}

func startMetricsServer(port string) *http.Server {
	mux := http.NewServeMux()
	mux.Handle("/metrics", promhttp.Handler())
	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		w.Write([]byte("OK"))
	})

	server := &http.Server{
		Addr:    ":" + port,
		Handler: mux,
	}

	go func() {
		log.Printf("Metrics server listening on :%s", port)
		if err := server.ListenAndServe(); err != http.ErrServerClosed {
			log.Fatalf("Metrics server error: %v", err)
		}
	}()

	return server
}

func startGRPCClient(targetAddr string, serviceName string) {
	// Wait for server to start
	time.Sleep(3 * time.Second)

	conn, err := grpc.NewClient(targetAddr,
		grpc.WithTransportCredentials(insecure.NewCredentials()),
		grpc.WithUnaryInterceptor(grpc_prometheus.UnaryClientInterceptor),
		grpc.WithStreamInterceptor(grpc_prometheus.StreamClientInterceptor),
		grpc.WithStatsHandler(otelgrpc.NewClientHandler()),
	)
	if err != nil {
		log.Printf("Failed to connect to %s: %v", targetAddr, err)
		return
	}
	defer conn.Close()

	client := pb.NewEchoServiceClient(conn)

	ticker := time.NewTicker(10 * time.Second)
	defer ticker.Stop()

	counter := 0
	for range ticker.C {
		counter++

		// Create a new span for each client call
		ctx, span := tracer.Start(context.Background(), "client.Echo",
			trace.WithSpanKind(trace.SpanKindClient),
		)

		ctx, cancel := context.WithTimeout(ctx, 5*time.Second)

		resp, err := client.Echo(ctx, &pb.EchoRequest{
			Message: fmt.Sprintf("Hello #%d from %s", counter, serviceName),
			Sender:  serviceName,
		})
		cancel()

		if err != nil {
			span.RecordError(err)
			log.Printf("Echo call failed: %v", err)
		} else {
			log.Printf("[%s] Got response from %s: %s", serviceName, resp.Responder, resp.Message)
		}
		span.End()
	}
}

func main() {
	ctx := context.Background()

	grpcPort := getEnv("GRPC_PORT", defaultGRPCPort)
	metricsPort := getEnv("METRICS_PORT", defaultMetricsPort)
	serviceName := getEnv("SERVICE_NAME", "go-service")
	peerAddr := getEnv("PEER_ADDRESS", "")

	// Initialize OpenTelemetry tracer
	tp, err := initTracer(ctx, serviceName)
	if err != nil {
		log.Printf("Warning: Failed to initialize tracer: %v", err)
	} else {
		defer func() {
			if err := tp.Shutdown(ctx); err != nil {
				log.Printf("Error shutting down tracer: %v", err)
			}
		}()
		log.Printf("OpenTelemetry tracer initialized for %s", serviceName)
	}

	// Start metrics server
	metricsServer := startMetricsServer(metricsPort)

	// Setup gRPC server with Prometheus and OTEL interceptors
	grpc_prometheus.EnableHandlingTimeHistogram()

	grpcServer := grpc.NewServer(
		grpc.UnaryInterceptor(grpc_prometheus.UnaryServerInterceptor),
		grpc.StreamInterceptor(grpc_prometheus.StreamServerInterceptor),
		grpc.StatsHandler(otelgrpc.NewServerHandler()),
	)

	pb.RegisterEchoServiceServer(grpcServer, &echoServer{serviceName: serviceName})
	grpc_prometheus.Register(grpcServer)
	reflection.Register(grpcServer)

	lis, err := net.Listen("tcp", ":"+grpcPort)
	if err != nil {
		log.Fatalf("Failed to listen: %v", err)
	}

	log.Printf("gRPC server %s listening on :%s", serviceName, grpcPort)

	// Start client if peer address is configured
	if peerAddr != "" {
		go startGRPCClient(peerAddr, serviceName)
	}

	// Handle graceful shutdown
	go func() {
		sigChan := make(chan os.Signal, 1)
		signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)
		<-sigChan

		log.Println("Shutting down...")
		grpcServer.GracefulStop()
		metricsServer.Shutdown(context.Background())
	}()

	if err := grpcServer.Serve(lis); err != nil {
		log.Fatalf("Failed to serve: %v", err)
	}
}

func getEnv(key, defaultVal string) string {
	if val := os.Getenv(key); val != "" {
		return val
	}
	return defaultVal
}
