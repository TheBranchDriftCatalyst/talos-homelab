package technitium

// LoginRequest represents the login API request
type LoginRequest struct {
	User string `json:"user"`
	Pass string `json:"pass"`
}

// LoginResponse represents the login API response
type LoginResponse struct {
	Status string `json:"status"`
	Token  string `json:"token"`
}

// AddRecordRequest represents the add record API request
type AddRecordRequest struct {
	Token  string `json:"token"`
	Zone   string `json:"zone"`
	Name   string `json:"name"`   // Subdomain or "@" for root
	Type   string `json:"type"`   // A, AAAA, CNAME, etc.
	Value  string `json:"value"`  // IP address for A records
	TTL    int    `json:"ttl"`    // Time to live in seconds
	IPAddr string `json:"ipaddr"` // Optional: for A/AAAA records, alias for Value
}

// UpdateRecordRequest represents the update record API request
type UpdateRecordRequest struct {
	Token    string `json:"token"`
	Zone     string `json:"zone"`
	Name     string `json:"name"`
	Type     string `json:"type"`
	NewValue string `json:"newValue"`
	Value    string `json:"value"` // Old value
	TTL      int    `json:"ttl"`
}

// DeleteRecordRequest represents the delete record API request
type DeleteRecordRequest struct {
	Token  string `json:"token"`
	Zone   string `json:"zone"`
	Name   string `json:"name"`
	Type   string `json:"type"`
	Value  string `json:"value"` // Optional: specific record value to delete
}

// GetRecordsRequest represents the get records API request
type GetRecordsRequest struct {
	Token  string `json:"token"`
	Domain string `json:"domain"` // Full domain name or zone
	Zone   string `json:"zone"`   // Zone name (alternative)
}

// RecordResponse represents a DNS record in the response
type RecordResponse struct {
	Name     string `json:"name"`
	Type     string `json:"type"`
	TTL      int    `json:"ttl"`
	RData    string `json:"rdata"` // Record data (IP for A records)
	Disabled bool   `json:"disabled"`
}

// GetRecordsResponse represents the get records API response
type GetRecordsResponse struct {
	Status  string           `json:"status"`
	Records []RecordResponse `json:"records"`
	Zone    ZoneInfo         `json:"zone"`
}

// ZoneInfo contains zone metadata
type ZoneInfo struct {
	Name     string `json:"name"`
	Type     string `json:"type"`
	Internal bool   `json:"internal"`
	Disabled bool   `json:"disabled"`
}

// APIResponse represents a generic API response
type APIResponse struct {
	Status   string `json:"status"`
	Response string `json:"response,omitempty"`
	Error    string `json:"errorMessage,omitempty"`
}

// ListZonesResponse represents the list zones API response
type ListZonesResponse struct {
	Status string     `json:"status"`
	Zones  []ZoneInfo `json:"zones"`
}
