package main

import (
	"context"
	"flag"
	"fmt"
	"log"
	"net"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/thebranchdriftcatalyst/carrierarr/pkg/agent"
	pb "github.com/thebranchdriftcatalyst/carrierarr/pkg/proto"
)

var (
	// Version is set at build time
	Version = "dev"

	// Flags
	controlPlaneAddr = flag.String("control-plane", "", "Control plane address (host:port)")
	nodeType         = flag.String("type", "gpu-worker", "Node type: gpu-worker, lighthouse")
	healthPort       = flag.Int("health-port", 8080, "Health check HTTP port")
	instanceID       = flag.String("instance-id", "", "EC2 instance ID (auto-detected if empty)")
	nebulaIP         = flag.String("nebula-ip", "", "Nebula VPN IP (auto-detected if empty)")
	publicIP         = flag.String("public-ip", "", "Public IP address")
	region           = flag.String("region", "", "AWS region")
	az               = flag.String("az", "", "AWS availability zone")

	// RabbitMQ flags
	rabbitmqURL   = flag.String("rabbitmq-url", "", "RabbitMQ connection URL (amqp://user:pass@host:port/vhost)")
	rabbitmqVHost = flag.String("rabbitmq-vhost", "agents", "RabbitMQ virtual host")
)

func main() {
	flag.Parse()

	log.SetFlags(log.LstdFlags | log.Lshortfile)
	log.Printf("worker-agent version %s starting...", Version)

	// Validate required flags
	if *controlPlaneAddr == "" {
		// Try environment variable
		*controlPlaneAddr = os.Getenv("CONTROL_PLANE_ADDR")
		if *controlPlaneAddr == "" {
			log.Fatal("--control-plane flag or CONTROL_PLANE_ADDR env var required")
		}
	}

	// RabbitMQ URL from flag or env
	if *rabbitmqURL == "" {
		*rabbitmqURL = os.Getenv("RABBITMQ_URL")
	}

	// Parse node type
	var pbNodeType pb.NodeType
	switch *nodeType {
	case "gpu-worker":
		pbNodeType = pb.NodeType_NODE_TYPE_GPU_WORKER
	case "lighthouse":
		pbNodeType = pb.NodeType_NODE_TYPE_LIGHTHOUSE
	default:
		log.Fatalf("Unknown node type: %s", *nodeType)
	}

	// Auto-detect identity if not provided
	if *instanceID == "" {
		*instanceID = detectInstanceID()
	}
	if *nebulaIP == "" {
		*nebulaIP = detectNebulaIP()
	}
	if *publicIP == "" {
		*publicIP = detectPublicIP()
	}
	if *region == "" {
		*region = os.Getenv("AWS_REGION")
	}

	log.Printf("Node identity: instance=%s nebula=%s public=%s region=%s az=%s",
		*instanceID, *nebulaIP, *publicIP, *region, *az)

	// Create agent client
	client := agent.NewClient(*controlPlaneAddr, pbNodeType)
	client.SetIdentity(*instanceID, *nebulaIP, *publicIP, *region, *az)

	// Create status collector
	hostname, _ := os.Hostname()
	statusCollector := agent.NewStatusCollector(hostname, pbNodeType)
	client.SetStatusCollector(statusCollector)

	// Create executor
	executor := agent.NewExecutor()
	client.SetExecutor(executor)

	// Set callbacks
	client.OnConnected = func() {
		log.Printf("Connected to control plane")
	}
	client.OnDisconnected = func() {
		log.Printf("Disconnected from control plane")
	}
	client.OnCommand = func(cmd *pb.Command) {
		log.Printf("Executing command: %s (%s)", cmd.CommandId, cmd.Type)
	}

	// Initialize RabbitMQ publisher if URL provided
	var rmqPublisher *agent.RabbitMQPublisher
	if *rabbitmqURL != "" {
		log.Printf("Initializing RabbitMQ publisher...")
		rmqConfig := agent.DefaultRabbitMQConfig()
		rmqConfig.URL = *rabbitmqURL
		rmqConfig.VHost = *rabbitmqVHost

		rmqPublisher = agent.NewRabbitMQPublisher(
			rmqConfig,
			*instanceID,
			*nodeType,
			*nebulaIP,
			*publicIP,
			*region,
			*az,
		)

		// Set status function to get current node status
		rmqPublisher.SetStatusFunc(func() *pb.NodeStatus {
			return statusCollector.Collect()
		})
	}

	// Start health check server
	go startHealthServer(*healthPort, client, rmqPublisher)

	// Setup signal handling
	ctx, cancel := context.WithCancel(context.Background())
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)

	go func() {
		sig := <-sigChan
		log.Printf("Received signal %v, shutting down...", sig)
		cancel()
	}()

	// Connect to RabbitMQ and register if configured
	if rmqPublisher != nil {
		log.Printf("Connecting to RabbitMQ...")
		if err := rmqPublisher.Connect(ctx); err != nil {
			log.Printf("Warning: Failed to connect to RabbitMQ: %v", err)
		} else {
			// Register with control plane via RabbitMQ
			if err := rmqPublisher.Register(ctx); err != nil {
				log.Printf("Warning: Failed to register via RabbitMQ: %v", err)
			} else {
				log.Printf("Registered via RabbitMQ")
			}
			// Start heartbeat loop
			rmqPublisher.StartHeartbeatLoop(ctx)
		}
	}

	// Run agent with auto-reconnection
	log.Printf("Connecting to control plane at %s...", *controlPlaneAddr)
	client.RunWithReconnect(ctx)

	// Graceful shutdown
	if rmqPublisher != nil {
		log.Printf("Stopping RabbitMQ publisher...")
		shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer shutdownCancel()
		if err := rmqPublisher.Stop(shutdownCtx); err != nil {
			log.Printf("Error stopping RabbitMQ publisher: %v", err)
		}
	}

	log.Printf("worker-agent shutdown complete")
}

func startHealthServer(port int, client *agent.Client, rmqPublisher *agent.RabbitMQPublisher) {
	mux := http.NewServeMux()

	// Health check endpoint
	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		grpcOK := client.IsConnected()
		rmqOK := rmqPublisher == nil || rmqPublisher.IsConnected()

		if grpcOK || rmqOK {
			w.WriteHeader(http.StatusOK)
			fmt.Fprintf(w, "ok (grpc=%v rmq=%v)\n", grpcOK, rmqOK)
		} else {
			w.WriteHeader(http.StatusServiceUnavailable)
			fmt.Fprintln(w, "disconnected")
		}
	})

	// Readiness endpoint
	mux.HandleFunc("/ready", func(w http.ResponseWriter, r *http.Request) {
		grpcOK := client.IsConnected()
		rmqOK := rmqPublisher == nil || rmqPublisher.IsConnected()

		if grpcOK || rmqOK {
			w.WriteHeader(http.StatusOK)
			fmt.Fprintln(w, "ready")
		} else {
			w.WriteHeader(http.StatusServiceUnavailable)
			fmt.Fprintln(w, "not ready")
		}
	})

	// Version endpoint
	mux.HandleFunc("/version", func(w http.ResponseWriter, r *http.Request) {
		fmt.Fprintf(w, "worker-agent %s\n", Version)
	})

	addr := fmt.Sprintf(":%d", port)
	log.Printf("Health server listening on %s", addr)
	if err := http.ListenAndServe(addr, mux); err != nil {
		log.Printf("Health server error: %v", err)
	}
}

func detectInstanceID() string {
	// Try EC2 metadata service
	client := &http.Client{Timeout: 2 * time.Second}

	// IMDSv2: Get token first
	tokenReq, _ := http.NewRequest("PUT", "http://169.254.169.254/latest/api/token", nil)
	tokenReq.Header.Set("X-aws-ec2-metadata-token-ttl-seconds", "21600")
	tokenResp, err := client.Do(tokenReq)
	if err != nil {
		// Fall back to hostname
		hostname, _ := os.Hostname()
		return hostname
	}
	defer tokenResp.Body.Close()

	token := make([]byte, 256)
	n, _ := tokenResp.Body.Read(token)
	token = token[:n]

	// Get instance ID
	req, _ := http.NewRequest("GET", "http://169.254.169.254/latest/meta-data/instance-id", nil)
	req.Header.Set("X-aws-ec2-metadata-token", string(token))
	resp, err := client.Do(req)
	if err != nil {
		hostname, _ := os.Hostname()
		return hostname
	}
	defer resp.Body.Close()

	instanceID := make([]byte, 64)
	n, _ = resp.Body.Read(instanceID)
	return string(instanceID[:n])
}

func detectNebulaIP() string {
	// Look for nebula1 interface
	iface, err := net.InterfaceByName("nebula1")
	if err != nil {
		return ""
	}

	addrs, err := iface.Addrs()
	if err != nil || len(addrs) == 0 {
		return ""
	}

	// Get first IP
	for _, addr := range addrs {
		if ipnet, ok := addr.(*net.IPNet); ok {
			if ipnet.IP.To4() != nil {
				return ipnet.IP.String()
			}
		}
	}
	return ""
}

func detectPublicIP() string {
	// Try EC2 metadata
	client := &http.Client{Timeout: 2 * time.Second}

	// IMDSv2: Get token first
	tokenReq, _ := http.NewRequest("PUT", "http://169.254.169.254/latest/api/token", nil)
	tokenReq.Header.Set("X-aws-ec2-metadata-token-ttl-seconds", "21600")
	tokenResp, err := client.Do(tokenReq)
	if err != nil {
		return ""
	}
	defer tokenResp.Body.Close()

	token := make([]byte, 256)
	n, _ := tokenResp.Body.Read(token)
	token = token[:n]

	// Get public IP
	req, _ := http.NewRequest("GET", "http://169.254.169.254/latest/meta-data/public-ipv4", nil)
	req.Header.Set("X-aws-ec2-metadata-token", string(token))
	resp, err := client.Do(req)
	if err != nil {
		return ""
	}
	defer resp.Body.Close()

	ip := make([]byte, 32)
	n, _ = resp.Body.Read(ip)
	return string(ip[:n])
}
