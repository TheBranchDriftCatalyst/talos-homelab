package config

import (
	"fmt"
	"os"
	"time"
)

// Config holds the application configuration
type Config struct {
	// Kubernetes configuration
	Kubeconfig     string
	InCluster      bool
	ResyncInterval time.Duration

	// Technitium configuration
	TechnitiumURL      string
	TechnitiumUsername string
	TechnitiumPassword string
	TechnitiumZone     string

	// DNS configuration
	NodeIP string
	TTL    int

	// Controller configuration
	Mode         string // "watch" or "poll"
	PollInterval time.Duration

	// Observability
	LogLevel    string
	MetricsPort int
	HealthPort  int
}

// LoadFromEnv loads configuration from environment variables
func LoadFromEnv() (*Config, error) {
	cfg := &Config{
		Kubeconfig:         os.Getenv("KUBECONFIG"),
		InCluster:          os.Getenv("IN_CLUSTER") == "true",
		ResyncInterval:     parseDuration(os.Getenv("RESYNC_INTERVAL"), 5*time.Minute),
		TechnitiumURL:      getEnvOrDefault("TECHNITIUM_URL", "http://technitium-dns.dns.svc.cluster.local:5380"),
		TechnitiumUsername: getEnvOrDefault("TECHNITIUM_USERNAME", "admin"),
		TechnitiumPassword: os.Getenv("TECHNITIUM_PASSWORD"),
		TechnitiumZone:     getEnvOrDefault("TECHNITIUM_ZONE", "talos00"),
		NodeIP:             getEnvOrDefault("NODE_IP", "192.168.1.54"),
		TTL:                parseInt(os.Getenv("DNS_TTL"), 300),
		Mode:               getEnvOrDefault("MODE", "watch"),
		PollInterval:       parseDuration(os.Getenv("POLL_INTERVAL"), 30*time.Second),
		LogLevel:           getEnvOrDefault("LOG_LEVEL", "info"),
		MetricsPort:        parseInt(os.Getenv("METRICS_PORT"), 9090),
		HealthPort:         parseInt(os.Getenv("HEALTH_PORT"), 8080),
	}

	// Validate required fields
	if cfg.TechnitiumPassword == "" {
		return nil, fmt.Errorf("TECHNITIUM_PASSWORD is required")
	}

	if cfg.Mode != "watch" && cfg.Mode != "poll" {
		return nil, fmt.Errorf("MODE must be either 'watch' or 'poll', got: %s", cfg.Mode)
	}

	return cfg, nil
}

func getEnvOrDefault(key, defaultValue string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return defaultValue
}

func parseInt(value string, defaultValue int) int {
	if value == "" {
		return defaultValue
	}
	var result int
	fmt.Sscanf(value, "%d", &result)
	if result == 0 {
		return defaultValue
	}
	return result
}

func parseDuration(value string, defaultValue time.Duration) time.Duration {
	if value == "" {
		return defaultValue
	}
	duration, err := time.ParseDuration(value)
	if err != nil {
		return defaultValue
	}
	return duration
}
