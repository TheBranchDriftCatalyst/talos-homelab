package grpc

import (
	"context"
	"fmt"
	"io"
	"log"
	"net"
	"time"

	"github.com/thebranchdriftcatalyst/carrierarr/pkg/fleet"
	pb "github.com/thebranchdriftcatalyst/carrierarr/pkg/proto"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/keepalive"
	"google.golang.org/grpc/peer"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/types/known/timestamppb"
)

// Server implements the AgentControl gRPC service
type Server struct {
	pb.UnimplementedAgentControlServer

	fleet  *fleet.Manager
	server *grpc.Server

	// Configuration
	HeartbeatInterval int32 // seconds
	StatusInterval    int32 // seconds
}

// NewServer creates a new gRPC server
func NewServer(fleetManager *fleet.Manager) *Server {
	return &Server{
		fleet:             fleetManager,
		HeartbeatInterval: 30,
		StatusInterval:    30,
	}
}

// Start starts the gRPC server
func (s *Server) Start(addr string) error {
	lis, err := net.Listen("tcp", addr)
	if err != nil {
		return fmt.Errorf("failed to listen: %w", err)
	}

	s.server = grpc.NewServer(
		grpc.KeepaliveParams(keepalive.ServerParameters{
			MaxConnectionIdle:     5 * time.Minute,
			MaxConnectionAge:      30 * time.Minute,
			MaxConnectionAgeGrace: 5 * time.Second,
			Time:                  1 * time.Minute,
			Timeout:               20 * time.Second,
		}),
		grpc.KeepaliveEnforcementPolicy(keepalive.EnforcementPolicy{
			MinTime:             10 * time.Second,
			PermitWithoutStream: true,
		}),
	)

	pb.RegisterAgentControlServer(s.server, s)

	log.Printf("[grpc] Server starting on %s", addr)
	return s.server.Serve(lis)
}

// Stop gracefully stops the gRPC server
func (s *Server) Stop() {
	if s.server != nil {
		s.server.GracefulStop()
	}
}

// Register handles agent registration
func (s *Server) Register(ctx context.Context, req *pb.RegisterRequest) (*pb.RegisterResponse, error) {
	// Get peer info for logging
	peerInfo, _ := peer.FromContext(ctx)
	log.Printf("[grpc] Register request from %v: node=%s type=%s",
		peerInfo.Addr, req.NodeId, req.NodeType)

	node, err := s.fleet.Register(req)
	if err != nil {
		return &pb.RegisterResponse{
			Accepted: false,
			Message:  err.Error(),
		}, nil
	}

	return &pb.RegisterResponse{
		Accepted:            true,
		Message:             "Registered successfully",
		AssignedId:          node.ID,
		HeartbeatIntervalSec: s.HeartbeatInterval,
		StatusIntervalSec:   s.StatusInterval,
	}, nil
}

// Connect handles bidirectional streaming between agent and control plane
func (s *Server) Connect(stream grpc.BidiStreamingServer[pb.AgentMessage, pb.ControlMessage]) error {
	// Get peer info
	peerInfo, _ := peer.FromContext(stream.Context())
	log.Printf("[grpc] Connect stream opened from %v", peerInfo.Addr)

	var nodeID string
	var node *fleet.Node

	// Channel for stream errors
	errChan := make(chan error, 1)

	// Goroutine to receive messages from agent
	go func() {
		for {
			msg, err := stream.Recv()
			if err == io.EOF {
				errChan <- nil
				return
			}
			if err != nil {
				errChan <- err
				return
			}

			switch payload := msg.Payload.(type) {
			case *pb.AgentMessage_Status:
				if nodeID == "" {
					nodeID = payload.Status.NodeId
					node = s.fleet.GetNode(nodeID)
					if node != nil {
						node.SetStreamActive(true)
						log.Printf("[grpc] Stream associated with node: %s", nodeID)
					}
				}
				if node != nil {
					s.fleet.UpdateStatus(nodeID, payload.Status)
				}

			case *pb.AgentMessage_CommandResult:
				log.Printf("[grpc] Command result from %s: cmd=%s success=%v",
					nodeID, payload.CommandResult.CommandId, payload.CommandResult.Success)

			case *pb.AgentMessage_Log:
				log.Printf("[grpc] Log from %s [%s]: %s",
					nodeID, payload.Log.Level, payload.Log.Message)
			}
		}
	}()

	// Main loop: send commands to agent
	for {
		select {
		case <-stream.Context().Done():
			log.Printf("[grpc] Stream context done for node: %s", nodeID)
			if node != nil {
				node.SetStreamActive(false)
				s.fleet.Disconnect(nodeID)
			}
			return stream.Context().Err()

		case err := <-errChan:
			log.Printf("[grpc] Stream error for node %s: %v", nodeID, err)
			if node != nil {
				node.SetStreamActive(false)
				s.fleet.Disconnect(nodeID)
			}
			if err != nil {
				return status.Errorf(codes.Internal, "stream error: %v", err)
			}
			return nil

		default:
			// Check for commands to send
			if node != nil {
				select {
				case cmd := <-node.CommandChan():
					if err := stream.Send(cmd); err != nil {
						log.Printf("[grpc] Error sending command to %s: %v", nodeID, err)
					}
				case <-time.After(100 * time.Millisecond):
					// No command, continue
				}
			} else {
				time.Sleep(100 * time.Millisecond)
			}
		}
	}
}

// Heartbeat handles heartbeat requests
func (s *Server) Heartbeat(ctx context.Context, req *pb.HeartbeatRequest) (*pb.HeartbeatResponse, error) {
	s.fleet.Heartbeat(req.NodeId)

	return &pb.HeartbeatResponse{
		Ok:         true,
		ServerTime: timestamppb.Now(),
	}, nil
}

// GetFleetStatus returns the current fleet status
func (s *Server) GetFleetStatus(ctx context.Context, req *pb.FleetStatusRequest) (*pb.FleetStatusResponse, error) {
	return s.fleet.GetFleetStatus(req), nil
}
