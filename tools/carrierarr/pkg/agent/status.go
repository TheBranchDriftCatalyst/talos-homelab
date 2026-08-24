package agent

import (
	"bufio"
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"os"
	"os/exec"
	"runtime"
	"strconv"
	"strings"
	"time"

	pb "github.com/thebranchdriftcatalyst/carrierarr/pkg/proto"
	"google.golang.org/protobuf/types/known/timestamppb"
)

// StatusCollector collects node status information
type StatusCollector struct {
	NodeID   string
	NodeType pb.NodeType

	// Service check endpoints
	OllamaURL string
	K3sURL    string

	// Tracking
	startTime     time.Time
	lastOllamaReq time.Time
}

// NewStatusCollector creates a new status collector
func NewStatusCollector(nodeID string, nodeType pb.NodeType) *StatusCollector {
	return &StatusCollector{
		NodeID:    nodeID,
		NodeType:  nodeType,
		OllamaURL: "http://localhost:11434",
		startTime: time.Now(),
	}
}

// Collect gathers current node status
func (c *StatusCollector) Collect() *pb.NodeStatus {
	status := &pb.NodeStatus{
		NodeId:        c.NodeID,
		Timestamp:     timestamppb.Now(),
		UptimeSeconds: int64(time.Since(c.startTime).Seconds()),
		IdleSeconds:   int64(time.Since(c.lastOllamaReq).Seconds()),
		Health:        pb.HealthState_HEALTH_STATE_HEALTHY,
	}

	// Collect service statuses
	status.Nebula = c.checkNebula()
	status.K3S = c.checkK3s()
	status.Ollama = c.checkOllama()
	status.Liqo = c.checkLiqo()

	// Collect resources
	status.Resources = c.collectResources()

	// Collect GPU status
	status.Gpus = c.collectGPUs()

	// Collect loaded models
	status.LoadedModels = c.collectOllamaModels()

	// Determine overall health
	status.Health = c.determineHealth(status)

	return status
}

func (c *StatusCollector) checkNebula() *pb.ServiceStatus {
	status := &pb.ServiceStatus{
		State: pb.ServiceState_SERVICE_STATE_STOPPED,
	}

	// Check if nebula interface exists
	iface, err := net.InterfaceByName("nebula1")
	if err != nil {
		status.Message = "nebula1 interface not found"
		return status
	}

	addrs, err := iface.Addrs()
	if err != nil || len(addrs) == 0 {
		status.Message = "nebula1 has no addresses"
		return status
	}

	status.State = pb.ServiceState_SERVICE_STATE_RUNNING
	return status
}

func (c *StatusCollector) checkK3s() *pb.ServiceStatus {
	status := &pb.ServiceStatus{
		State: pb.ServiceState_SERVICE_STATE_STOPPED,
	}

	// Check k3s-agent or k3s service
	var serviceName string
	if c.NodeType == pb.NodeType_NODE_TYPE_LIGHTHOUSE {
		serviceName = "k3s"
	} else {
		serviceName = "k3s-agent"
	}

	cmd := exec.Command("systemctl", "is-active", serviceName)
	output, err := cmd.Output()
	if err != nil {
		status.State = pb.ServiceState_SERVICE_STATE_NOT_INSTALLED
		status.Message = "k3s not installed or not running"
		return status
	}

	if strings.TrimSpace(string(output)) == "active" {
		status.State = pb.ServiceState_SERVICE_STATE_RUNNING
	} else {
		status.State = pb.ServiceState_SERVICE_STATE_STOPPED
		status.Message = string(output)
	}

	return status
}

func (c *StatusCollector) checkOllama() *pb.ServiceStatus {
	status := &pb.ServiceStatus{
		State: pb.ServiceState_SERVICE_STATE_STOPPED,
	}

	// Check if ollama is responding
	client := &http.Client{Timeout: 2 * time.Second}
	resp, err := client.Get(c.OllamaURL + "/api/tags")
	if err != nil {
		// Check if service is installed but not running
		cmd := exec.Command("systemctl", "is-enabled", "ollama")
		if err := cmd.Run(); err != nil {
			status.State = pb.ServiceState_SERVICE_STATE_NOT_INSTALLED
			status.Message = "ollama not installed"
		} else {
			status.Message = "ollama not responding"
		}
		return status
	}
	defer resp.Body.Close()

	if resp.StatusCode == 200 {
		status.State = pb.ServiceState_SERVICE_STATE_RUNNING
	} else {
		status.Message = fmt.Sprintf("ollama returned %d", resp.StatusCode)
	}

	return status
}

func (c *StatusCollector) checkLiqo() *pb.ServiceStatus {
	status := &pb.ServiceStatus{
		State: pb.ServiceState_SERVICE_STATE_NOT_INSTALLED,
	}

	// Only check on lighthouse
	if c.NodeType != pb.NodeType_NODE_TYPE_LIGHTHOUSE {
		return status
	}

	// Check if liqo pods are running
	cmd := exec.Command("kubectl", "get", "pods", "-n", "liqo-system", "-o", "json")
	output, err := cmd.Output()
	if err != nil {
		status.Message = "unable to check liqo"
		return status
	}

	var podList struct {
		Items []struct {
			Status struct {
				Phase string `json:"phase"`
			} `json:"status"`
		} `json:"items"`
	}

	if err := json.Unmarshal(output, &podList); err != nil {
		status.Message = "unable to parse liqo status"
		return status
	}

	if len(podList.Items) == 0 {
		status.State = pb.ServiceState_SERVICE_STATE_NOT_INSTALLED
		return status
	}

	running := 0
	for _, pod := range podList.Items {
		if pod.Status.Phase == "Running" {
			running++
		}
	}

	if running == len(podList.Items) {
		status.State = pb.ServiceState_SERVICE_STATE_RUNNING
	} else {
		status.State = pb.ServiceState_SERVICE_STATE_STARTING
		status.Message = fmt.Sprintf("%d/%d pods running", running, len(podList.Items))
	}

	return status
}

func (c *StatusCollector) collectResources() *pb.ResourceUsage {
	usage := &pb.ResourceUsage{}

	// CPU - read from /proc/stat
	// Simplified: just use runtime info
	usage.CpuPercent = 0 // Would need to track over time

	// Memory - read from /proc/meminfo
	if file, err := os.Open("/proc/meminfo"); err == nil {
		defer file.Close()
		scanner := bufio.NewScanner(file)
		for scanner.Scan() {
			line := scanner.Text()
			fields := strings.Fields(line)
			if len(fields) < 2 {
				continue
			}
			value, _ := strconv.ParseInt(fields[1], 10, 64)
			switch fields[0] {
			case "MemTotal:":
				usage.MemoryTotalMb = value / 1024
			case "MemAvailable:":
				usage.MemoryUsedMb = usage.MemoryTotalMb - (value / 1024)
			}
		}
	} else {
		// Fallback for non-Linux
		var m runtime.MemStats
		runtime.ReadMemStats(&m)
		usage.MemoryUsedMb = int64(m.Alloc / 1024 / 1024)
	}

	// Disk - check /var/lib/ollama mount
	// Would use syscall.Statfs in real implementation

	return usage
}

func (c *StatusCollector) collectGPUs() []*pb.GPUStatus {
	var gpus []*pb.GPUStatus

	// Run nvidia-smi
	cmd := exec.Command("nvidia-smi",
		"--query-gpu=index,name,memory.used,memory.total,utilization.gpu,temperature.gpu",
		"--format=csv,noheader,nounits")
	output, err := cmd.Output()
	if err != nil {
		return gpus // No GPU or nvidia-smi not available
	}

	lines := strings.Split(strings.TrimSpace(string(output)), "\n")
	for _, line := range lines {
		fields := strings.Split(line, ", ")
		if len(fields) < 6 {
			continue
		}

		idx, _ := strconv.Atoi(strings.TrimSpace(fields[0]))
		memUsed, _ := strconv.ParseInt(strings.TrimSpace(fields[2]), 10, 64)
		memTotal, _ := strconv.ParseInt(strings.TrimSpace(fields[3]), 10, 64)
		util, _ := strconv.ParseFloat(strings.TrimSpace(fields[4]), 64)
		temp, _ := strconv.Atoi(strings.TrimSpace(fields[5]))

		gpus = append(gpus, &pb.GPUStatus{
			Index:              int32(idx),
			Name:               strings.TrimSpace(fields[1]),
			MemoryUsedMb:       memUsed,
			MemoryTotalMb:      memTotal,
			UtilizationPercent: util,
			TemperatureC:       int32(temp),
		})
	}

	return gpus
}

func (c *StatusCollector) collectOllamaModels() []*pb.OllamaModel {
	var models []*pb.OllamaModel

	client := &http.Client{Timeout: 5 * time.Second}
	resp, err := client.Get(c.OllamaURL + "/api/tags")
	if err != nil {
		return models
	}
	defer resp.Body.Close()

	var result struct {
		Models []struct {
			Name string `json:"name"`
			Size int64  `json:"size"`
		} `json:"models"`
	}

	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return models
	}

	// Check which models are loaded (via /api/ps)
	loadedModels := make(map[string]bool)
	if psResp, err := client.Get(c.OllamaURL + "/api/ps"); err == nil {
		defer psResp.Body.Close()
		var psResult struct {
			Models []struct {
				Name string `json:"name"`
			} `json:"models"`
		}
		if json.NewDecoder(psResp.Body).Decode(&psResult) == nil {
			for _, m := range psResult.Models {
				loadedModels[m.Name] = true
				// Track activity
				c.lastOllamaReq = time.Now()
			}
		}
	}

	for _, m := range result.Models {
		models = append(models, &pb.OllamaModel{
			Name:            m.Name,
			SizeBytes:       m.Size,
			CurrentlyLoaded: loadedModels[m.Name],
		})
	}

	return models
}

func (c *StatusCollector) determineHealth(status *pb.NodeStatus) pb.HealthState {
	// Critical services must be running
	if status.Nebula.State != pb.ServiceState_SERVICE_STATE_RUNNING {
		return pb.HealthState_HEALTH_STATE_UNHEALTHY
	}

	if status.K3S.State != pb.ServiceState_SERVICE_STATE_RUNNING &&
		status.K3S.State != pb.ServiceState_SERVICE_STATE_NOT_INSTALLED {
		return pb.HealthState_HEALTH_STATE_UNHEALTHY
	}

	// For GPU workers, Ollama should be running
	if c.NodeType == pb.NodeType_NODE_TYPE_GPU_WORKER {
		if status.Ollama.State != pb.ServiceState_SERVICE_STATE_RUNNING {
			return pb.HealthState_HEALTH_STATE_DEGRADED
		}
	}

	// For lighthouse, Liqo should be running
	if c.NodeType == pb.NodeType_NODE_TYPE_LIGHTHOUSE {
		if status.Liqo.State != pb.ServiceState_SERVICE_STATE_RUNNING {
			return pb.HealthState_HEALTH_STATE_DEGRADED
		}
	}

	return pb.HealthState_HEALTH_STATE_HEALTHY
}
