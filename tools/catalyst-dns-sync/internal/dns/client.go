package dns

import (
	"bufio"
	"context"
	"crypto/tls"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/url"
	"os"
	"strings"
	"sync"
	"time"

	"github.com/talos-fix/catalyst-dns-sync/internal/config"
	"github.com/talos-fix/catalyst-dns-sync/internal/metrics"
)

// DNSClient is the interface for DNS operations
type DNSClient interface {
	// CreateOrUpdateRecord creates or updates a DNS A record
	CreateOrUpdateRecord(ctx context.Context, hostname string) error
	// DeleteRecord removes a DNS A record
	DeleteRecord(ctx context.Context, hostname string) error
	// ListRecords returns all managed DNS records
	ListRecords(ctx context.Context) ([]string, error)
	// IsHealthy checks if the DNS service is reachable
	IsHealthy(ctx context.Context) bool
}

// TechnitiumClient implements DNSClient for Technitium DNS Server
type TechnitiumClient struct {
	serverURL string
	apiToken  string
	zone      string
	ipAddress string
	ttl       int
	client    *http.Client
	logger    *slog.Logger
}

// NewTechnitiumClient creates a new Technitium DNS client
func NewTechnitiumClient(cfg *config.Config, logger *slog.Logger) *TechnitiumClient {
	// Create HTTP client with custom transport (skip TLS verify for self-signed certs)
	transport := &http.Transport{
		TLSClientConfig: &tls.Config{InsecureSkipVerify: true},
	}

	return &TechnitiumClient{
		serverURL: cfg.DNSServerURL,
		apiToken:  cfg.DNSAPIToken,
		zone:      cfg.DNSZone,
		ipAddress: cfg.DNSIPAddress,
		ttl:       cfg.DNSTTLDefault,
		client: &http.Client{
			Transport: transport,
			Timeout:   30 * time.Second,
		},
		logger: logger,
	}
}

// CreateOrUpdateRecord creates or updates a DNS A record in Technitium
func (c *TechnitiumClient) CreateOrUpdateRecord(ctx context.Context, hostname string) error {
	start := time.Now()
	endpoint := "/api/zones/records/add"

	params := url.Values{}
	params.Set("token", c.apiToken)
	params.Set("domain", hostname)
	params.Set("zone", c.zone)
	params.Set("type", "A")
	params.Set("ipAddress", c.ipAddress)
	params.Set("ttl", fmt.Sprintf("%d", c.ttl))
	params.Set("overwrite", "true")

	reqURL := fmt.Sprintf("%s%s?%s", c.serverURL, endpoint, params.Encode())

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, reqURL, nil)
	if err != nil {
		metrics.APIRequestsTotal.WithLabelValues(endpoint, "GET", "error").Inc()
		return fmt.Errorf("creating request: %w", err)
	}

	resp, err := c.client.Do(req)
	if err != nil {
		metrics.APIRequestsTotal.WithLabelValues(endpoint, "GET", "error").Inc()
		return fmt.Errorf("executing request: %w", err)
	}
	defer resp.Body.Close()

	duration := time.Since(start).Seconds()
	metrics.APIRequestDuration.WithLabelValues(endpoint, "GET").Observe(duration)
	metrics.APIRequestsTotal.WithLabelValues(endpoint, "GET", fmt.Sprintf("%d", resp.StatusCode)).Inc()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("API returned status %d: %s", resp.StatusCode, string(body))
	}

	// Parse response to check for success
	var result struct {
		Status string `json:"status"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return fmt.Errorf("decoding response: %w", err)
	}

	if result.Status != "ok" {
		return fmt.Errorf("API returned status: %s", result.Status)
	}

	c.logger.Info("DNS record created/updated",
		"hostname", hostname,
		"ip", c.ipAddress,
		"zone", c.zone,
		"duration", duration,
	)

	metrics.RecordCreated(c.zone)
	return nil
}

// DeleteRecord removes a DNS A record from Technitium
func (c *TechnitiumClient) DeleteRecord(ctx context.Context, hostname string) error {
	start := time.Now()
	endpoint := "/api/zones/records/delete"

	params := url.Values{}
	params.Set("token", c.apiToken)
	params.Set("domain", hostname)
	params.Set("zone", c.zone)
	params.Set("type", "A")
	params.Set("ipAddress", c.ipAddress)

	reqURL := fmt.Sprintf("%s%s?%s", c.serverURL, endpoint, params.Encode())

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, reqURL, nil)
	if err != nil {
		metrics.APIRequestsTotal.WithLabelValues(endpoint, "GET", "error").Inc()
		return fmt.Errorf("creating request: %w", err)
	}

	resp, err := c.client.Do(req)
	if err != nil {
		metrics.APIRequestsTotal.WithLabelValues(endpoint, "GET", "error").Inc()
		return fmt.Errorf("executing request: %w", err)
	}
	defer resp.Body.Close()

	duration := time.Since(start).Seconds()
	metrics.APIRequestDuration.WithLabelValues(endpoint, "GET").Observe(duration)
	metrics.APIRequestsTotal.WithLabelValues(endpoint, "GET", fmt.Sprintf("%d", resp.StatusCode)).Inc()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("API returned status %d: %s", resp.StatusCode, string(body))
	}

	c.logger.Info("DNS record deleted",
		"hostname", hostname,
		"zone", c.zone,
		"duration", duration,
	)

	metrics.RecordDeleted(c.zone)
	return nil
}

// ListRecords returns all A records in the zone
func (c *TechnitiumClient) ListRecords(ctx context.Context) ([]string, error) {
	endpoint := "/api/zones/records/get"

	params := url.Values{}
	params.Set("token", c.apiToken)
	params.Set("zone", c.zone)
	params.Set("domain", c.zone)
	params.Set("listZone", "true")

	reqURL := fmt.Sprintf("%s%s?%s", c.serverURL, endpoint, params.Encode())

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, reqURL, nil)
	if err != nil {
		return nil, fmt.Errorf("creating request: %w", err)
	}

	resp, err := c.client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("executing request: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("API returned status %d: %s", resp.StatusCode, string(body))
	}

	var result struct {
		Response struct {
			Records []struct {
				Name   string `json:"name"`
				Type   string `json:"type"`
				RData  string `json:"rData"`
			} `json:"records"`
		} `json:"response"`
	}

	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return nil, fmt.Errorf("decoding response: %w", err)
	}

	var hostnames []string
	for _, record := range result.Response.Records {
		if record.Type == "A" && record.RData == c.ipAddress {
			hostnames = append(hostnames, record.Name)
		}
	}

	return hostnames, nil
}

// IsHealthy checks if the Technitium DNS API is reachable
func (c *TechnitiumClient) IsHealthy(ctx context.Context) bool {
	endpoint := "/api/user/session/get"

	params := url.Values{}
	params.Set("token", c.apiToken)

	reqURL := fmt.Sprintf("%s%s?%s", c.serverURL, endpoint, params.Encode())

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, reqURL, nil)
	if err != nil {
		return false
	}

	resp, err := c.client.Do(req)
	if err != nil {
		return false
	}
	defer resp.Body.Close()

	return resp.StatusCode == http.StatusOK
}

// HostsFileClient implements DNSClient for local /etc/hosts updates (dev mode)
type HostsFileClient struct {
	hostsPath string
	ipAddress string
	zone      string
	logger    *slog.Logger
	mu        sync.Mutex
	managed   map[string]bool // Track managed hostnames
}

const (
	beginMarker = "# BEGIN CATALYST-DNS-SYNC MANAGED BLOCK"
	endMarker   = "# END CATALYST-DNS-SYNC MANAGED BLOCK"
)

// NewHostsFileClient creates a new /etc/hosts client
func NewHostsFileClient(cfg *config.Config, logger *slog.Logger) *HostsFileClient {
	return &HostsFileClient{
		hostsPath: "/etc/hosts",
		ipAddress: cfg.DNSIPAddress,
		zone:      cfg.DNSZone,
		logger:    logger,
		managed:   make(map[string]bool),
	}
}

// CreateOrUpdateRecord adds a hostname to /etc/hosts
func (c *HostsFileClient) CreateOrUpdateRecord(ctx context.Context, hostname string) error {
	c.mu.Lock()
	defer c.mu.Unlock()

	c.managed[hostname] = true
	return c.writeHostsFile()
}

// DeleteRecord removes a hostname from /etc/hosts
func (c *HostsFileClient) DeleteRecord(ctx context.Context, hostname string) error {
	c.mu.Lock()
	defer c.mu.Unlock()

	delete(c.managed, hostname)
	return c.writeHostsFile()
}

// ListRecords returns all managed hostnames
func (c *HostsFileClient) ListRecords(ctx context.Context) ([]string, error) {
	c.mu.Lock()
	defer c.mu.Unlock()

	var hostnames []string
	for hostname := range c.managed {
		hostnames = append(hostnames, hostname)
	}
	return hostnames, nil
}

// IsHealthy checks if /etc/hosts is writable
func (c *HostsFileClient) IsHealthy(ctx context.Context) bool {
	// Check if we can open the file for writing
	// This requires sudo access in most cases
	f, err := os.OpenFile(c.hostsPath, os.O_RDWR, 0644)
	if err != nil {
		return false
	}
	f.Close()
	return true
}

// writeHostsFile rewrites the managed block in /etc/hosts
func (c *HostsFileClient) writeHostsFile() error {
	// Read existing content
	content, err := os.ReadFile(c.hostsPath)
	if err != nil {
		return fmt.Errorf("reading hosts file: %w", err)
	}

	// Parse and remove existing managed block
	var newContent strings.Builder
	scanner := bufio.NewScanner(strings.NewReader(string(content)))
	inManagedBlock := false

	for scanner.Scan() {
		line := scanner.Text()
		if strings.HasPrefix(line, beginMarker) {
			inManagedBlock = true
			continue
		}
		if strings.HasPrefix(line, endMarker) {
			inManagedBlock = false
			continue
		}
		if !inManagedBlock {
			newContent.WriteString(line)
			newContent.WriteString("\n")
		}
	}

	// Build new managed block
	if len(c.managed) > 0 {
		newContent.WriteString("\n")
		newContent.WriteString(beginMarker)
		newContent.WriteString("\n")
		newContent.WriteString("# Auto-generated by catalyst-dns-sync (dev mode)\n")
		for hostname := range c.managed {
			newContent.WriteString(fmt.Sprintf("%s  %s\n", c.ipAddress, hostname))
		}
		newContent.WriteString(endMarker)
		newContent.WriteString("\n")
	}

	// Write back
	if err := os.WriteFile(c.hostsPath, []byte(newContent.String()), 0644); err != nil {
		return fmt.Errorf("writing hosts file: %w", err)
	}

	c.logger.Info("Updated /etc/hosts",
		"hostnames", len(c.managed),
	)

	metrics.ManagedHostnames.Set(float64(len(c.managed)))
	return nil
}

// SetHostnames batch sets all managed hostnames (used for sync)
func (c *HostsFileClient) SetHostnames(hostnames []string) error {
	c.mu.Lock()
	defer c.mu.Unlock()

	c.managed = make(map[string]bool)
	for _, h := range hostnames {
		c.managed[h] = true
	}
	return c.writeHostsFile()
}
