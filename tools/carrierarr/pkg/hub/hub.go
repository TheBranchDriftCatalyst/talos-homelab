// Package hub manages WebSocket client connections and message broadcasting
package hub

import (
	"log"
	"sync"
	"time"

	"github.com/gorilla/websocket"
	"github.com/thebranchdriftcatalyst/ec2-agent/pkg/protocol"
)

const (
	// Time allowed to write a message to the peer
	writeWait = 10 * time.Second

	// Time allowed to read the next pong message from the peer
	pongWait = 60 * time.Second

	// Send pings to peer with this period (must be less than pongWait)
	pingPeriod = (pongWait * 9) / 10

	// Maximum message size allowed from peer
	maxMessageSize = 8192
)

// Client represents a WebSocket client connection
type Client struct {
	hub  *Hub
	conn *websocket.Conn
	send chan []byte

	// Subscriptions - which workers this client wants updates for
	subscriptions map[string]bool
	subMu         sync.RWMutex
}

// Hub maintains the set of active clients and broadcasts messages
type Hub struct {
	// Registered clients
	clients map[*Client]bool

	// Inbound messages from clients
	Inbound chan ClientMessage

	// Broadcast channel for outbound messages
	Broadcast chan protocol.OutboundMessage

	// Register requests from clients
	register chan *Client

	// Unregister requests from clients
	unregister chan *Client

	mu sync.RWMutex
}

// ClientMessage wraps an inbound message with its source client
type ClientMessage struct {
	Client  *Client
	Message *protocol.InboundMessage
}

// New creates a new Hub
func New() *Hub {
	return &Hub{
		clients:    make(map[*Client]bool),
		Inbound:    make(chan ClientMessage, 256),
		Broadcast:  make(chan protocol.OutboundMessage, 256),
		register:   make(chan *Client),
		unregister: make(chan *Client),
	}
}

// Run starts the hub's main loop
func (h *Hub) Run() {
	ticker := time.NewTicker(pingPeriod)
	defer ticker.Stop()

	for {
		select {
		case client := <-h.register:
			h.mu.Lock()
			h.clients[client] = true
			h.mu.Unlock()
			log.Printf("[Hub] Client registered, total: %d", len(h.clients))

		case client := <-h.unregister:
			h.mu.Lock()
			if _, ok := h.clients[client]; ok {
				delete(h.clients, client)
				close(client.send)
			}
			h.mu.Unlock()
			log.Printf("[Hub] Client unregistered, total: %d", len(h.clients))

		case message := <-h.Broadcast:
			h.broadcast(message)

		case <-ticker.C:
			// Ping all clients periodically
			h.mu.RLock()
			for client := range h.clients {
				select {
				case client.send <- []byte(`{"type":"ping"}`):
				default:
					// Client buffer full, will be cleaned up
				}
			}
			h.mu.RUnlock()
		}
	}
}

// broadcast sends a message to all subscribed clients
func (h *Hub) broadcast(msg protocol.OutboundMessage) {
	data := msg.ToJSON()

	h.mu.RLock()
	defer h.mu.RUnlock()

	for client := range h.clients {
		// Check if client is subscribed to this target
		if msg.Target != "" && !client.isSubscribed(msg.Target) {
			continue
		}

		select {
		case client.send <- data:
		default:
			// Client buffer full, close connection
			close(client.send)
			delete(h.clients, client)
		}
	}
}

// ClientCount returns the number of connected clients
func (h *Hub) ClientCount() int {
	h.mu.RLock()
	defer h.mu.RUnlock()
	return len(h.clients)
}

// NewClient creates a new client and registers it with the hub
func (h *Hub) NewClient(conn *websocket.Conn) *Client {
	client := &Client{
		hub:           h,
		conn:          conn,
		send:          make(chan []byte, 256),
		subscriptions: make(map[string]bool),
	}
	h.register <- client
	return client
}

// Subscribe adds a target to the client's subscriptions
func (c *Client) Subscribe(target string) {
	c.subMu.Lock()
	defer c.subMu.Unlock()
	c.subscriptions[target] = true
	// Empty string means subscribe to all
	if target == "" || target == "*" {
		c.subscriptions["*"] = true
	}
}

// Unsubscribe removes a target from the client's subscriptions
func (c *Client) Unsubscribe(target string) {
	c.subMu.Lock()
	defer c.subMu.Unlock()
	delete(c.subscriptions, target)
}

// isSubscribed checks if client is subscribed to a target
func (c *Client) isSubscribed(target string) bool {
	c.subMu.RLock()
	defer c.subMu.RUnlock()
	// Subscribed to all?
	if c.subscriptions["*"] {
		return true
	}
	return c.subscriptions[target]
}

// ReadPump pumps messages from the WebSocket connection to the hub
func (c *Client) ReadPump() {
	defer func() {
		c.hub.unregister <- c
		c.conn.Close()
	}()

	c.conn.SetReadLimit(maxMessageSize)
	c.conn.SetReadDeadline(time.Now().Add(pongWait))
	c.conn.SetPongHandler(func(string) error {
		c.conn.SetReadDeadline(time.Now().Add(pongWait))
		return nil
	})

	for {
		_, message, err := c.conn.ReadMessage()
		if err != nil {
			if websocket.IsUnexpectedCloseError(err, websocket.CloseGoingAway, websocket.CloseAbnormalClosure) {
				log.Printf("[Hub] WebSocket error: %v", err)
			}
			break
		}

		msg, err := protocol.ParseInbound(message)
		if err != nil {
			log.Printf("[Hub] Failed to parse message: %v", err)
			continue
		}

		// Handle subscribe messages directly
		if msg.Type == protocol.TypeSubscribe {
			c.Subscribe(msg.Target)
			continue
		}

		// Handle ping
		if msg.Type == protocol.TypePing {
			c.send <- []byte(`{"type":"pong"}`)
			continue
		}

		// Forward other messages to hub
		c.hub.Inbound <- ClientMessage{Client: c, Message: msg}
	}
}

// WritePump pumps messages from the hub to the WebSocket connection
func (c *Client) WritePump() {
	ticker := time.NewTicker(pingPeriod)
	defer func() {
		ticker.Stop()
		c.conn.Close()
	}()

	for {
		select {
		case message, ok := <-c.send:
			c.conn.SetWriteDeadline(time.Now().Add(writeWait))
			if !ok {
				c.conn.WriteMessage(websocket.CloseMessage, []byte{})
				return
			}

			w, err := c.conn.NextWriter(websocket.TextMessage)
			if err != nil {
				return
			}
			w.Write(message)

			// Batch pending messages
			n := len(c.send)
			for i := 0; i < n; i++ {
				w.Write([]byte{'\n'})
				w.Write(<-c.send)
			}

			if err := w.Close(); err != nil {
				return
			}

		case <-ticker.C:
			c.conn.SetWriteDeadline(time.Now().Add(writeWait))
			if err := c.conn.WriteMessage(websocket.PingMessage, nil); err != nil {
				return
			}
		}
	}
}

// Send sends a message directly to this client
func (c *Client) Send(msg protocol.OutboundMessage) {
	select {
	case c.send <- msg.ToJSON():
	default:
		// Buffer full
	}
}
