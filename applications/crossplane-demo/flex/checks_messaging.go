package main

import (
	"context"
	"encoding/json"
	"fmt"
	"net"
	"time"

	amqp "github.com/rabbitmq/amqp091-go"
	"github.com/redis/go-redis/v9"
)

// dialAMQP opens a RabbitMQ connection with a bounded TCP dial timeout so a
// dead broker fails fast instead of hanging past the check timeout.
func dialAMQP(url string) (*amqp.Connection, error) {
	return amqp.DialConfig(url, amqp.Config{
		Heartbeat: 10 * time.Second,
		Locale:    "en_US",
		Dial: func(network, addr string) (net.Conn, error) {
			return net.DialTimeout(network, addr, 8*time.Second)
		},
	})
}

// checkRabbitMQ: ensure queue -> publish -> basic.get consume -> verify body.
func checkRabbitMQ(ctx context.Context) (string, bool, error) {
	url := env("RABBITMQ_URL")
	if url == "" {
		return "RABBITMQ_URL not set", true, nil
	}
	queue := envDefault("RABBITMQ_QUEUE", "demo")

	conn, err := dialAMQP(url)
	if err != nil {
		return "", false, fmt.Errorf("dial: %w", err)
	}
	defer conn.Close()

	ch, err := conn.Channel()
	if err != nil {
		return "", false, fmt.Errorf("channel: %w", err)
	}
	defer ch.Close()

	if _, err := ch.QueueDeclare(queue, true, false, false, false, nil); err != nil {
		return "", false, fmt.Errorf("declare: %w", err)
	}

	body := "flex-" + randHex(8)
	if err := ch.PublishWithContext(ctx, "", queue, false, false, amqp.Publishing{
		ContentType:  "text/plain",
		Body:         []byte(body),
		DeliveryMode: amqp.Persistent,
	}); err != nil {
		return "", false, fmt.Errorf("publish: %w", err)
	}

	// basic.get, retrying briefly to allow the broker to route the message.
	deadline := time.Now().Add(5 * time.Second)
	for {
		msg, ok, err := ch.Get(queue, true)
		if err != nil {
			return "", false, fmt.Errorf("get: %w", err)
		}
		if ok {
			if string(msg.Body) != body {
				return "", false, fmt.Errorf("body mismatch: sent %q got %q", body, msg.Body)
			}
			return fmt.Sprintf("queue %q publish/consume ok", queue), false, nil
		}
		if time.Now().After(deadline) {
			return "", false, fmt.Errorf("no message consumed from %q", queue)
		}
		select {
		case <-ctx.Done():
			return "", false, ctx.Err()
		case <-time.After(200 * time.Millisecond):
		}
	}
}

// newRedis builds a Dragonfly/Redis client from REDIS_ADDR / REDIS_PASSWORD.
func newRedis() *redis.Client {
	return redis.NewClient(&redis.Options{
		Addr:        env("REDIS_ADDR"),
		Password:    env("REDIS_PASSWORD"),
		DialTimeout: 8 * time.Second,
	})
}

// checkDragonfly: SET a random value -> GET -> compare.
func checkDragonfly(ctx context.Context) (string, bool, error) {
	if env("REDIS_ADDR") == "" {
		return "REDIS_ADDR not set", true, nil
	}
	rdb := newRedis()
	defer rdb.Close()

	key := "flex:probe:" + randHex(4)
	val := randHex(8)
	if err := rdb.Set(ctx, key, val, time.Minute).Err(); err != nil {
		return "", false, fmt.Errorf("set: %w", err)
	}
	got, err := rdb.Get(ctx, key).Result()
	if err != nil {
		return "", false, fmt.Errorf("get: %w", err)
	}
	if got != val {
		return "", false, fmt.Errorf("mismatch: set %q got %q", val, got)
	}
	return fmt.Sprintf("key %q set/get ok", key), false, nil
}

// checkCelery: publish a Celery protocol-v2 task onto the celery queue (via the
// RabbitMQ broker) and poll Dragonfly for a marker key that the worker sets
// after processing. OK when the marker appears. Requires both RABBITMQ_URL and
// REDIS_ADDR; if either is missing the check is skipped.
func checkCelery(ctx context.Context) (string, bool, error) {
	url := env("RABBITMQ_URL")
	if url == "" || env("REDIS_ADDR") == "" {
		return "RABBITMQ_URL and/or REDIS_ADDR not set", true, nil
	}
	queue := envDefault("CELERY_QUEUE", "celery")
	taskName := envDefault("CELERY_TASK", "demo.flex")
	markerKey := envDefault("CELERY_MARKER_KEY", "celery:flex:done")

	// Clear any stale marker so we observe a fresh completion.
	rdb := newRedis()
	defer rdb.Close()
	_ = rdb.Del(ctx, markerKey).Err()

	// Publish the Celery task.
	conn, err := dialAMQP(url)
	if err != nil {
		return "", false, fmt.Errorf("dial: %w", err)
	}
	defer conn.Close()
	ch, err := conn.Channel()
	if err != nil {
		return "", false, fmt.Errorf("channel: %w", err)
	}
	defer ch.Close()
	if _, err := ch.QueueDeclare(queue, true, false, false, false, nil); err != nil {
		return "", false, fmt.Errorf("declare: %w", err)
	}

	taskID := randHex(16)
	// Celery message protocol v2: body = [args, kwargs, embed].
	body, _ := json.Marshal([]interface{}{
		[]interface{}{},          // args
		map[string]interface{}{}, // kwargs
		map[string]interface{}{ // embed
			"callbacks": nil, "errbacks": nil, "chain": nil, "chord": nil,
		},
	})
	if err := ch.PublishWithContext(ctx, "", queue, false, false, amqp.Publishing{
		ContentType:     "application/json",
		ContentEncoding: "utf-8",
		CorrelationId:   taskID,
		DeliveryMode:    amqp.Persistent,
		Headers: amqp.Table{
			"lang":       "py",
			"task":       taskName,
			"id":         taskID,
			"root_id":    taskID,
			"parent_id":  nil,
			"group":      nil,
			"argsrepr":   "()",
			"kwargsrepr": "{}",
		},
		Body: body,
	}); err != nil {
		return "", false, fmt.Errorf("publish: %w", err)
	}

	// Poll Dragonfly for the worker's completion marker.
	deadline := time.Now().Add(30 * time.Second)
	for {
		v, err := rdb.Get(ctx, markerKey).Result()
		if err == nil {
			return fmt.Sprintf("task %s dispatched, marker %q=%q observed", taskName, markerKey, v), false, nil
		}
		if err != redis.Nil {
			return "", false, fmt.Errorf("marker get: %w", err)
		}
		if time.Now().After(deadline) {
			return "", false, fmt.Errorf("marker %q not set within 30s (worker not processing?)", markerKey)
		}
		select {
		case <-ctx.Done():
			return "", false, ctx.Err()
		case <-time.After(1 * time.Second):
		}
	}
}
