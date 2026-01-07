// ec2-agent provides a WebSocket interface for controlling EC2/Fargate workers
package main

import (
	"context"
	"encoding/json"
	"flag"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/ec2"
	"github.com/aws/aws-sdk-go-v2/service/ecs"
	"github.com/gorilla/websocket"
	"github.com/thebranchdriftcatalyst/ec2-agent/pkg/hub"
	"github.com/thebranchdriftcatalyst/ec2-agent/pkg/monitor"
	"github.com/thebranchdriftcatalyst/ec2-agent/pkg/process"
	"github.com/thebranchdriftcatalyst/ec2-agent/pkg/protocol"
)

var (
	addr         = flag.String("addr", ":8090", "HTTP server address")
	workerScript = flag.String("script", "", "Path to worker control script")
	ec2Tags      = flag.String("ec2-tags", "", "EC2 instance tags to monitor (JSON object)")
	ecsCluster   = flag.String("ecs-cluster", "", "ECS cluster to monitor")
	pollInterval = flag.Duration("poll", 30*time.Second, "Status poll interval")
)

var upgrader = websocket.Upgrader{
	ReadBufferSize:  1024,
	WriteBufferSize: 1024,
	CheckOrigin: func(r *http.Request) bool {
		return true // Allow all origins for development
	},
}

// Server ties together all components
type Server struct {
	hub        *hub.Hub
	procMgr    *process.Manager
	ec2Monitor *monitor.EC2Monitor
	fgMonitor  *monitor.FargateMonitor
}

func main() {
	flag.Parse()

	log.SetFlags(log.LstdFlags | log.Lshortfile)
	log.Printf("ec2-agent starting on %s", *addr)

	// Create hub
	h := hub.New()
	go h.Run()

	// Create process manager
	var procMgr *process.Manager
	if *workerScript != "" {
		procMgr = process.New(*workerScript, func(msg protocol.OutboundMessage) {
			h.Broadcast <- msg
		})
		log.Printf("Process manager initialized with script: %s", *workerScript)
	}

	server := &Server{
		hub:     h,
		procMgr: procMgr,
	}

	// Initialize AWS clients and monitors
	ctx := context.Background()
	awsCfg, err := config.LoadDefaultConfig(ctx)
	if err != nil {
		log.Printf("Warning: Failed to load AWS config: %v", err)
	} else {
		// EC2 monitor
		if *ec2Tags != "" {
			var tags map[string]string
			if err := json.Unmarshal([]byte(*ec2Tags), &tags); err != nil {
				log.Printf("Warning: Failed to parse ec2-tags: %v", err)
			} else {
				ec2Client := ec2.NewFromConfig(awsCfg)
				server.ec2Monitor = monitor.NewEC2Monitor(monitor.EC2Config{
					Client:   ec2Client,
					Interval: *pollInterval,
					Tags:     tags,
				})
				server.ec2Monitor.OnStatusUpdate = func(workers []protocol.WorkerStatus) {
					h.Broadcast <- protocol.NewStatusMessage(workers)
				}
				go server.ec2Monitor.Start(ctx)
				log.Printf("EC2 monitor started with tags: %v", tags)
			}
		}

		// Fargate monitor
		if *ecsCluster != "" {
			ecsClient := ecs.NewFromConfig(awsCfg)
			server.fgMonitor = monitor.NewFargateMonitor(monitor.FargateConfig{
				Client:   ecsClient,
				Interval: *pollInterval,
				Cluster:  *ecsCluster,
			})
			server.fgMonitor.OnStatusUpdate = func(workers []protocol.WorkerStatus) {
				h.Broadcast <- protocol.NewStatusMessage(workers)
			}
			go server.fgMonitor.Start(ctx)
			log.Printf("Fargate monitor started for cluster: %s", *ecsCluster)
		}
	}

	// Handle inbound messages
	go server.handleInbound()

	// HTTP routes
	http.HandleFunc("/ws", server.handleWebSocket)
	http.HandleFunc("/health", server.handleHealth)
	http.HandleFunc("/api/status", server.handleStatus)

	// Start HTTP server
	httpServer := &http.Server{
		Addr:         *addr,
		ReadTimeout:  15 * time.Second,
		WriteTimeout: 15 * time.Second,
	}

	// Graceful shutdown
	go func() {
		sigCh := make(chan os.Signal, 1)
		signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)
		<-sigCh

		log.Println("Shutting down...")
		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()

		if server.ec2Monitor != nil {
			server.ec2Monitor.Stop()
		}
		if server.fgMonitor != nil {
			server.fgMonitor.Stop()
		}

		httpServer.Shutdown(ctx)
	}()

	log.Printf("Server ready at http://localhost%s", *addr)
	log.Printf("  WebSocket: ws://localhost%s/ws", *addr)
	log.Printf("  Health:    http://localhost%s/health", *addr)
	log.Printf("  Status:    http://localhost%s/api/status", *addr)

	if err := httpServer.ListenAndServe(); err != http.ErrServerClosed {
		log.Fatalf("HTTP server error: %v", err)
	}
}

// handleWebSocket upgrades HTTP connections to WebSocket
func (s *Server) handleWebSocket(w http.ResponseWriter, r *http.Request) {
	conn, err := upgrader.Upgrade(w, r, nil)
	if err != nil {
		log.Printf("WebSocket upgrade failed: %v", err)
		return
	}

	client := s.hub.NewClient(conn)

	// Subscribe to all by default
	client.Subscribe("*")

	// Send current status on connect
	go func() {
		workers := s.getAllStatus()
		if len(workers) > 0 {
			client.Send(protocol.NewStatusMessage(workers))
		}
	}()

	// Start read/write pumps
	go client.WritePump()
	client.ReadPump()
}

// handleInbound processes inbound messages from clients
func (s *Server) handleInbound() {
	for msg := range s.hub.Inbound {
		switch msg.Message.Type {
		case protocol.TypeCommand:
			s.handleCommand(msg)
		}
	}
}

// handleCommand executes a command from a client
func (s *Server) handleCommand(msg hub.ClientMessage) {
	cmd := msg.Message

	log.Printf("Received command: %s %v (target: %s)", cmd.Command, cmd.Args, cmd.Target)

	if s.procMgr == nil {
		msg.Client.Send(protocol.NewErrorMessage(cmd.Target, "No worker script configured"))
		return
	}

	target := cmd.Target
	if target == "" {
		target = "default"
	}

	// Check for kill command
	if cmd.Command == "kill" {
		if err := s.procMgr.Kill(target); err != nil {
			msg.Client.Send(protocol.NewErrorMessage(target, err.Error()))
		}
		return
	}

	// Execute command in goroutine
	go func() {
		ctx := context.Background()
		_, err := s.procMgr.Execute(ctx, target, cmd.Command, cmd.Args)
		if err != nil {
			s.hub.Broadcast <- protocol.NewErrorMessage(target, err.Error())
		}
	}()
}

// handleHealth returns health status
func (s *Server) handleHealth(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"status":  "healthy",
		"clients": s.hub.ClientCount(),
	})
}

// handleStatus returns current worker status
func (s *Server) handleStatus(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"workers":   s.getAllStatus(),
		"timestamp": time.Now(),
	})
}

// getAllStatus gets status from all monitors
func (s *Server) getAllStatus() []protocol.WorkerStatus {
	workers := make([]protocol.WorkerStatus, 0)
	if s.ec2Monitor != nil {
		workers = append(workers, s.ec2Monitor.GetStatus()...)
	}
	if s.fgMonitor != nil {
		workers = append(workers, s.fgMonitor.GetStatus()...)
	}
	return workers
}
