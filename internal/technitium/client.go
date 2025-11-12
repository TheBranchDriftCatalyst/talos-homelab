package technitium

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"time"

	"github.com/rs/zerolog"
	"github.com/yourusername/catalyst-dns-sync/internal/metrics"
)

// Client represents a Technitium DNS API client
type Client struct {
	baseURL    string
	username   string
	password   string
	token      string
	httpClient *http.Client
	logger     zerolog.Logger
}

// NewClient creates a new Technitium API client
func NewClient(baseURL, username, password string, logger zerolog.Logger) *Client {
	return &Client{
		baseURL:  baseURL,
		username: username,
		password: password,
		httpClient: &http.Client{
			Timeout: 10 * time.Second,
		},
		logger: logger.With().Str("component", "technitium-client").Logger(),
	}
}

// Login authenticates with the Technitium API and obtains a token
func (c *Client) Login() error {
	start := time.Now()
	defer func() {
		metrics.APIRequestDuration.WithLabelValues("POST", "/api/user/login").Observe(time.Since(start).Seconds())
	}()

	data := url.Values{}
	data.Set("user", c.username)
	data.Set("pass", c.password)

	resp, err := c.httpClient.PostForm(c.baseURL+"/api/user/login", data)
	if err != nil {
		metrics.APIErrorsTotal.WithLabelValues("POST", "/api/user/login", "network_error").Inc()
		c.logger.Error().Err(err).Msg("Failed to login to Technitium API")
		return fmt.Errorf("login request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		metrics.APIErrorsTotal.WithLabelValues("POST", "/api/user/login", fmt.Sprintf("%d", resp.StatusCode)).Inc()
		return fmt.Errorf("login failed with status: %d", resp.StatusCode)
	}

	var loginResp LoginResponse
	if err := json.NewDecoder(resp.Body).Decode(&loginResp); err != nil {
		return fmt.Errorf("failed to decode login response: %w", err)
	}

	if loginResp.Status != "ok" {
		return fmt.Errorf("login failed: %s", loginResp.Status)
	}

	c.token = loginResp.Token
	c.logger.Info().Msg("Successfully authenticated with Technitium API")
	return nil
}

// AddRecord adds a DNS A record
func (c *Client) AddRecord(zone, name, ip string, ttl int) error {
	start := time.Now()
	endpoint := "/api/zones/records/add"
	defer func() {
		metrics.APIRequestDuration.WithLabelValues("POST", endpoint).Observe(time.Since(start).Seconds())
	}()

	data := url.Values{}
	data.Set("token", c.token)
	data.Set("zone", zone)
	data.Set("name", name)
	data.Set("type", "A")
	data.Set("value", ip)
	data.Set("ttl", fmt.Sprintf("%d", ttl))

	resp, err := c.httpClient.PostForm(c.baseURL+endpoint, data)
	if err != nil {
		metrics.APIErrorsTotal.WithLabelValues("POST", endpoint, "network_error").Inc()
		c.logger.Error().Err(err).
			Str("zone", zone).
			Str("name", name).
			Str("ip", ip).
			Msg("Failed to add DNS record")
		return fmt.Errorf("add record request failed: %w", err)
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)

	if resp.StatusCode != http.StatusOK {
		metrics.APIErrorsTotal.WithLabelValues("POST", endpoint, fmt.Sprintf("%d", resp.StatusCode)).Inc()
		return fmt.Errorf("add record failed with status %d: %s", resp.StatusCode, string(body))
	}

	var apiResp APIResponse
	if err := json.Unmarshal(body, &apiResp); err != nil {
		return fmt.Errorf("failed to decode response: %w", err)
	}

	if apiResp.Status != "ok" {
		return fmt.Errorf("add record failed: %s", apiResp.Error)
	}

	c.logger.Info().
		Str("zone", zone).
		Str("name", name).
		Str("ip", ip).
		Int("ttl", ttl).
		Msg("DNS record added")

	return nil
}

// UpdateRecord updates an existing DNS A record
func (c *Client) UpdateRecord(zone, name, oldIP, newIP string, ttl int) error {
	start := time.Now()
	endpoint := "/api/zones/records/update"
	defer func() {
		metrics.APIRequestDuration.WithLabelValues("POST", endpoint).Observe(time.Since(start).Seconds())
	}()

	data := url.Values{}
	data.Set("token", c.token)
	data.Set("zone", zone)
	data.Set("name", name)
	data.Set("type", "A")
	data.Set("value", oldIP)
	data.Set("newValue", newIP)
	data.Set("ttl", fmt.Sprintf("%d", ttl))

	resp, err := c.httpClient.PostForm(c.baseURL+endpoint, data)
	if err != nil {
		metrics.APIErrorsTotal.WithLabelValues("POST", endpoint, "network_error").Inc()
		return fmt.Errorf("update record request failed: %w", err)
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)

	if resp.StatusCode != http.StatusOK {
		metrics.APIErrorsTotal.WithLabelValues("POST", endpoint, fmt.Sprintf("%d", resp.StatusCode)).Inc()
		return fmt.Errorf("update record failed with status %d: %s", resp.StatusCode, string(body))
	}

	var apiResp APIResponse
	if err := json.Unmarshal(body, &apiResp); err != nil {
		return fmt.Errorf("failed to decode response: %w", err)
	}

	if apiResp.Status != "ok" {
		return fmt.Errorf("update record failed: %s", apiResp.Error)
	}

	c.logger.Info().
		Str("zone", zone).
		Str("name", name).
		Str("old_ip", oldIP).
		Str("new_ip", newIP).
		Msg("DNS record updated")

	return nil
}

// DeleteRecord deletes a DNS A record
func (c *Client) DeleteRecord(zone, name, ip string) error {
	start := time.Now()
	endpoint := "/api/zones/records/delete"
	defer func() {
		metrics.APIRequestDuration.WithLabelValues("POST", endpoint).Observe(time.Since(start).Seconds())
	}()

	data := url.Values{}
	data.Set("token", c.token)
	data.Set("zone", zone)
	data.Set("name", name)
	data.Set("type", "A")
	if ip != "" {
		data.Set("value", ip)
	}

	resp, err := c.httpClient.PostForm(c.baseURL+endpoint, data)
	if err != nil {
		metrics.APIErrorsTotal.WithLabelValues("POST", endpoint, "network_error").Inc()
		return fmt.Errorf("delete record request failed: %w", err)
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)

	if resp.StatusCode != http.StatusOK {
		metrics.APIErrorsTotal.WithLabelValues("POST", endpoint, fmt.Sprintf("%d", resp.StatusCode)).Inc()
		return fmt.Errorf("delete record failed with status %d: %s", resp.StatusCode, string(body))
	}

	var apiResp APIResponse
	if err := json.Unmarshal(body, &apiResp); err != nil {
		return fmt.Errorf("failed to decode response: %w", err)
	}

	if apiResp.Status != "ok" {
		return fmt.Errorf("delete record failed: %s", apiResp.Error)
	}

	c.logger.Info().
		Str("zone", zone).
		Str("name", name).
		Str("ip", ip).
		Msg("DNS record deleted")

	return nil
}

// GetRecords retrieves all records for a zone
func (c *Client) GetRecords(zone string) ([]RecordResponse, error) {
	start := time.Now()
	endpoint := "/api/zones/records/get"
	defer func() {
		metrics.APIRequestDuration.WithLabelValues("GET", endpoint).Observe(time.Since(start).Seconds())
	}()

	data := url.Values{}
	data.Set("token", c.token)
	data.Set("domain", zone)

	resp, err := c.httpClient.PostForm(c.baseURL+endpoint, data)
	if err != nil {
		metrics.APIErrorsTotal.WithLabelValues("GET", endpoint, "network_error").Inc()
		return nil, fmt.Errorf("get records request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		metrics.APIErrorsTotal.WithLabelValues("GET", endpoint, fmt.Sprintf("%d", resp.StatusCode)).Inc()
		return nil, fmt.Errorf("get records failed with status: %d", resp.StatusCode)
	}

	var getResp GetRecordsResponse
	if err := json.NewDecoder(resp.Body).Decode(&getResp); err != nil {
		return nil, fmt.Errorf("failed to decode response: %w", err)
	}

	if getResp.Status != "ok" {
		return nil, fmt.Errorf("get records failed")
	}

	return getResp.Records, nil
}

// EnsureRecord ensures a DNS record exists with the correct value
// Returns action taken: "created", "updated", "skipped"
func (c *Client) EnsureRecord(zone, name, ip string, ttl int) (string, error) {
	records, err := c.GetRecords(zone)
	if err != nil {
		return "", fmt.Errorf("failed to get existing records: %w", err)
	}

	// Check if record exists
	for _, record := range records {
		if record.Name == name && record.Type == "A" {
			if record.RData == ip {
				// Record exists with correct value
				return "skipped", nil
			}
			// Record exists but with wrong IP, update it
			if err := c.UpdateRecord(zone, name, record.RData, ip, ttl); err != nil {
				return "", err
			}
			return "updated", nil
		}
	}

	// Record doesn't exist, create it
	if err := c.AddRecord(zone, name, ip, ttl); err != nil {
		return "", err
	}
	return "created", nil
}

// Ping checks if the Technitium API is reachable
func (c *Client) Ping() error {
	resp, err := c.httpClient.Get(c.baseURL + "/api/ping")
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("ping failed with status: %d", resp.StatusCode)
	}

	return nil
}
