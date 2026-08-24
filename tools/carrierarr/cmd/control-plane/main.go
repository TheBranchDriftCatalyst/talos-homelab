package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/thebranchdriftcatalyst/carrierarr/pkg/fleet"
	"github.com/thebranchdriftcatalyst/carrierarr/pkg/grpc"
	pb "github.com/thebranchdriftcatalyst/carrierarr/pkg/proto"
	"google.golang.org/protobuf/encoding/protojson"
)

var (
	// Version is set at build time
	Version = "dev"

	// Flags
	grpcAddr      = flag.String("grpc-addr", ":50051", "gRPC server address")
	httpAddr      = flag.String("http-addr", ":8090", "HTTP API server address")
	wsAddr        = flag.String("ws-addr", ":8091", "WebSocket server address (legacy)")
	staleTimeout  = flag.Duration("stale-timeout", 2*time.Minute, "Node stale timeout")

	// RabbitMQ flags
	rabbitmqURL        = flag.String("rabbitmq-url", "", "RabbitMQ connection URL (amqp://user:pass@host:port/vhost)")
	rabbitmqVHost      = flag.String("rabbitmq-vhost", "agents", "RabbitMQ virtual host")
	autoTerminateDead  = flag.Bool("auto-terminate-dead", false, "Auto-terminate nodes after dead threshold (opt-in)")
	deadThreshold      = flag.Duration("dead-threshold", 5*time.Minute, "Time after which node is marked dead")
)

func main() {
	flag.Parse()

	log.SetFlags(log.LstdFlags | log.Lshortfile)
	log.Printf("control-plane version %s starting...", Version)

	// Create fleet manager
	fleetManager := fleet.NewManager()
	fleetManager.StaleTimeout = *staleTimeout

	// Set up fleet callbacks
	fleetManager.OnNodeConnected = func(node *fleet.Node) {
		log.Printf("[fleet] Node connected: %s (%s) at %s",
			node.ID, node.Type, node.NebulaIP)
	}

	fleetManager.OnNodeDisconnected = func(node *fleet.Node) {
		log.Printf("[fleet] Node disconnected: %s", node.ID)
	}

	fleetManager.OnNodeStatusUpdate = func(node *fleet.Node, status *pb.NodeStatus) {
		log.Printf("[fleet] Status update from %s: health=%s gpus=%d models=%d",
			node.ID, status.Health, len(status.Gpus), len(status.LoadedModels))
	}

	// Start context for background services
	ctx, cancel := context.WithCancel(context.Background())

	// Initialize RabbitMQ consumer if URL provided
	var rmqConsumer *fleet.RabbitMQConsumer
	if *rabbitmqURL != "" {
		log.Printf("Initializing RabbitMQ consumer...")
		rmqConfig := fleet.DefaultRabbitMQConfig()
		rmqConfig.URL = *rabbitmqURL
		rmqConfig.StaleThreshold = *staleTimeout
		rmqConfig.DeadThreshold = *deadThreshold
		rmqConfig.AutoTerminateOnDead = *autoTerminateDead

		rmqConsumer = fleet.NewRabbitMQConsumer(rmqConfig, fleetManager)

		if err := rmqConsumer.Connect(ctx); err != nil {
			log.Printf("Warning: Failed to connect to RabbitMQ: %v", err)
		} else {
			log.Printf("Connected to RabbitMQ at %s", *rabbitmqURL)
			if err := rmqConsumer.Start(ctx); err != nil {
				log.Printf("Warning: Failed to start RabbitMQ consumers: %v", err)
			} else {
				log.Printf("RabbitMQ consumers started (auto-terminate: %v)", *autoTerminateDead)
			}
		}
	} else {
		log.Printf("RabbitMQ not configured, using gRPC-only mode")
	}

	// Create gRPC server
	grpcServer := grpc.NewServer(fleetManager)

	// Start gRPC server
	go func() {
		log.Printf("gRPC server starting on %s", *grpcAddr)
		if err := grpcServer.Start(*grpcAddr); err != nil {
			log.Fatalf("gRPC server failed: %v", err)
		}
	}()

	// Start HTTP API server
	go startHTTPServer(*httpAddr, fleetManager)

	// Start fleet cleanup goroutine (only if RabbitMQ not configured, as RabbitMQ has its own TTL checker)
	if rmqConsumer == nil {
		go fleetManager.StartCleanup(ctx)
	}

	// Setup signal handling
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)

	sig := <-sigChan
	log.Printf("Received signal %v, shutting down...", sig)

	cancel()

	// Stop RabbitMQ consumer
	if rmqConsumer != nil {
		log.Printf("Stopping RabbitMQ consumer...")
		if err := rmqConsumer.Stop(); err != nil {
			log.Printf("Error stopping RabbitMQ consumer: %v", err)
		}
	}

	grpcServer.Stop()

	log.Printf("control-plane shutdown complete")
}

func startHTTPServer(addr string, fleetManager *fleet.Manager) {
	mux := http.NewServeMux()

	// Health check
	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		fmt.Fprintln(w, "ok")
	})

	// Version
	mux.HandleFunc("/version", func(w http.ResponseWriter, r *http.Request) {
		json.NewEncoder(w).Encode(map[string]string{
			"version": Version,
		})
	})

	// Fleet status
	mux.HandleFunc("/api/v1/fleet", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")

		status := fleetManager.GetFleetStatus(&pb.FleetStatusRequest{})

		// Use protojson for proper JSON encoding
		marshaler := protojson.MarshalOptions{
			EmitUnpopulated: true,
			UseProtoNames:   true,
		}
		data, err := marshaler.Marshal(status)
		if err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
		w.Write(data)
	})

	// List nodes
	mux.HandleFunc("/api/v1/nodes", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")

		nodes := fleetManager.ListNodes()
		result := make([]map[string]interface{}, len(nodes))

		for i, node := range nodes {
			result[i] = map[string]interface{}{
				"id":           node.ID,
				"type":         node.Type.String(),
				"instance_id":  node.InstanceID,
				"nebula_ip":    node.NebulaIP,
				"public_ip":    node.PublicIP,
				"connected":    node.Connected,
				"last_seen":    node.LastSeen.Format(time.RFC3339),
				"stream_active": node.StreamActive,
			}
			if node.Status != nil {
				result[i]["health"] = node.Status.Health.String()
				result[i]["uptime_seconds"] = node.Status.UptimeSeconds
				result[i]["idle_seconds"] = node.Status.IdleSeconds
				result[i]["gpu_count"] = len(node.Status.Gpus)
				result[i]["loaded_models"] = len(node.Status.LoadedModels)
			}
		}

		json.NewEncoder(w).Encode(result)
	})

	// Get specific node
	mux.HandleFunc("/api/v1/nodes/", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")

		// Extract node ID from path
		nodeID := r.URL.Path[len("/api/v1/nodes/"):]
		if nodeID == "" {
			http.Error(w, "node ID required", http.StatusBadRequest)
			return
		}

		node := fleetManager.GetNode(nodeID)
		if node == nil {
			http.Error(w, "node not found", http.StatusNotFound)
			return
		}

		result := map[string]interface{}{
			"id":           node.ID,
			"type":         node.Type.String(),
			"instance_id":  node.InstanceID,
			"nebula_ip":    node.NebulaIP,
			"public_ip":    node.PublicIP,
			"region":       node.Region,
			"az":           node.AZ,
			"labels":       node.Labels,
			"connected":    node.Connected,
			"connected_at": node.ConnectedAt.Format(time.RFC3339),
			"last_seen":    node.LastSeen.Format(time.RFC3339),
			"stream_active": node.StreamActive,
		}

		if node.Status != nil {
			result["status"] = map[string]interface{}{
				"health":         node.Status.Health.String(),
				"uptime_seconds": node.Status.UptimeSeconds,
				"idle_seconds":   node.Status.IdleSeconds,
			}

			if node.Status.Resources != nil {
				result["resources"] = map[string]interface{}{
					"cpu_percent":     node.Status.Resources.CpuPercent,
					"memory_used_mb":  node.Status.Resources.MemoryUsedMb,
					"memory_total_mb": node.Status.Resources.MemoryTotalMb,
				}
			}

			if len(node.Status.Gpus) > 0 {
				gpus := make([]map[string]interface{}, len(node.Status.Gpus))
				for i, gpu := range node.Status.Gpus {
					gpus[i] = map[string]interface{}{
						"index":          gpu.Index,
						"name":           gpu.Name,
						"memory_used_mb": gpu.MemoryUsedMb,
						"memory_total_mb": gpu.MemoryTotalMb,
						"utilization":    gpu.UtilizationPercent,
						"temperature_c":  gpu.TemperatureC,
					}
				}
				result["gpus"] = gpus
			}

			if len(node.Status.LoadedModels) > 0 {
				models := make([]map[string]interface{}, len(node.Status.LoadedModels))
				for i, model := range node.Status.LoadedModels {
					models[i] = map[string]interface{}{
						"name":             model.Name,
						"size_bytes":       model.SizeBytes,
						"currently_loaded": model.CurrentlyLoaded,
					}
				}
				result["models"] = models
			}
		}

		json.NewEncoder(w).Encode(result)
	})

	// Send command to node
	mux.HandleFunc("/api/v1/command", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}

		var req struct {
			NodeID  string            `json:"node_id"`
			Type    string            `json:"type"`
			Args    map[string]string `json:"args"`
			Timeout int32             `json:"timeout"`
		}

		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}

		// Map command type
		cmdType, ok := pb.CommandType_value["COMMAND_TYPE_"+req.Type]
		if !ok {
			http.Error(w, "unknown command type", http.StatusBadRequest)
			return
		}

		cmd := &pb.Command{
			CommandId:      fmt.Sprintf("cmd-%d", time.Now().UnixNano()),
			Type:           pb.CommandType(cmdType),
			Args:           req.Args,
			TimeoutSeconds: req.Timeout,
		}

		if req.NodeID == "*" {
			// Broadcast to all nodes
			sent := fleetManager.BroadcastCommand(cmd, pb.NodeType_NODE_TYPE_UNSPECIFIED)
			json.NewEncoder(w).Encode(map[string]interface{}{
				"command_id": cmd.CommandId,
				"sent_to":    sent,
			})
		} else {
			// Send to specific node
			if fleetManager.SendCommand(req.NodeID, cmd) {
				json.NewEncoder(w).Encode(map[string]interface{}{
					"command_id": cmd.CommandId,
					"sent":       true,
				})
			} else {
				http.Error(w, "failed to send command (node not connected?)", http.StatusBadGateway)
			}
		}
	})

	// Statistics
	mux.HandleFunc("/api/v1/stats", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")

		status := fleetManager.GetFleetStatus(&pb.FleetStatusRequest{})
		summary := status.Summary

		json.NewEncoder(w).Encode(map[string]interface{}{
			"total_nodes":    summary.TotalNodes,
			"healthy_nodes":  summary.HealthyNodes,
			"unhealthy_nodes": summary.UnhealthyNodes,
			"gpu_nodes":      summary.GpuNodes,
			"total_gpus":     summary.TotalGpus,
			"connected":      fleetManager.ConnectedCount(),
		})
	})

	log.Printf("HTTP API server starting on %s", addr)
	if err := http.ListenAndServe(addr, mux); err != nil {
		log.Fatalf("HTTP server failed: %v", err)
	}
}
