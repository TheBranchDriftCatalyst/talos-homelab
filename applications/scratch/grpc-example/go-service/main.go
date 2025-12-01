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

	pb "grpc-example/gen/echopb"
)

const (
	defaultGRPCPort    = "50051"
	defaultMetricsPort = "9090"
)

type echoServer struct {
	pb.UnimplementedEchoServiceServer
	serviceName string
}

func (s *echoServer) Echo(ctx context.Context, req *pb.EchoRequest) (*pb.EchoResponse, error) {
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
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)

		resp, err := client.Echo(ctx, &pb.EchoRequest{
			Message: fmt.Sprintf("Hello #%d from %s", counter, serviceName),
			Sender:  serviceName,
		})
		cancel()

		if err != nil {
			log.Printf("Echo call failed: %v", err)
			continue
		}

		log.Printf("[%s] Got response from %s: %s", serviceName, resp.Responder, resp.Message)
	}
}

func main() {
	grpcPort := getEnv("GRPC_PORT", defaultGRPCPort)
	metricsPort := getEnv("METRICS_PORT", defaultMetricsPort)
	serviceName := getEnv("SERVICE_NAME", "go-service")
	peerAddr := getEnv("PEER_ADDRESS", "")

	// Start metrics server
	metricsServer := startMetricsServer(metricsPort)

	// Setup gRPC server with Prometheus interceptors
	grpc_prometheus.EnableHandlingTimeHistogram()

	grpcServer := grpc.NewServer(
		grpc.UnaryInterceptor(grpc_prometheus.UnaryServerInterceptor),
		grpc.StreamInterceptor(grpc_prometheus.StreamServerInterceptor),
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
