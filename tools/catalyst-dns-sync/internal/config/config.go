package config

import (
	"os"
	"strconv"
	"time"
)

// Config holds all configuration for the DNS sync controller
type Config struct {
	// DNS Server configuration
	DNSServerURL  string
	DNSAPIToken   string
	DNSZone       string
	DNSIPAddress  string
	DNSTTLDefault int

	// Logging configuration
	LogLevel  string
	LogFormat string

	// Server addresses
	MetricsBindAddress string
	HealthProbeAddress string

	// Mode configuration
	DevMode bool

	// Controller configuration
	SyncInterval time.Duration
}

// LoadFromEnv loads configuration from environment variables
func LoadFromEnv() *Config {
	return &Config{
		// DNS Server configuration
		DNSServerURL:  getEnv("DNS_SERVER_URL", "https://dns.talos00:5380"),
		DNSAPIToken:   getEnv("DNS_API_TOKEN", ""),
		DNSZone:       getEnv("DNS_ZONE", "talos00"),
		DNSIPAddress:  getEnv("DNS_IP_ADDRESS", "192.168.1.54"),
		DNSTTLDefault: getEnvInt("DNS_TTL_DEFAULT", 300),

		// Logging configuration
		LogLevel:  getEnv("LOG_LEVEL", "info"),
		LogFormat: getEnv("LOG_FORMAT", "json"),

		// Server addresses
		MetricsBindAddress: getEnv("METRICS_BIND_ADDRESS", ":8080"),
		HealthProbeAddress: getEnv("HEALTH_PROBE_ADDRESS", ":8081"),

		// Mode configuration
		DevMode: getEnvBool("DEV_MODE", false),

		// Controller configuration
		SyncInterval: getEnvDuration("SYNC_INTERVAL", 30*time.Second),
	}
}

// getEnv returns the value of an environment variable or a default value
func getEnv(key, defaultValue string) string {
	if value, exists := os.LookupEnv(key); exists {
		return value
	}
	return defaultValue
}

// getEnvInt returns the integer value of an environment variable or a default value
func getEnvInt(key string, defaultValue int) int {
	if value, exists := os.LookupEnv(key); exists {
		if intVal, err := strconv.Atoi(value); err == nil {
			return intVal
		}
	}
	return defaultValue
}

// getEnvBool returns the boolean value of an environment variable or a default value
func getEnvBool(key string, defaultValue bool) bool {
	if value, exists := os.LookupEnv(key); exists {
		if boolVal, err := strconv.ParseBool(value); err == nil {
			return boolVal
		}
	}
	return defaultValue
}

// getEnvDuration returns the duration value of an environment variable or a default value
func getEnvDuration(key string, defaultValue time.Duration) time.Duration {
	if value, exists := os.LookupEnv(key); exists {
		if dur, err := time.ParseDuration(value); err == nil {
			return dur
		}
	}
	return defaultValue
}
