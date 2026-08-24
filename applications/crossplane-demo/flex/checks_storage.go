package main

import (
	"bytes"
	"context"
	"crypto/tls"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	"github.com/ClickHouse/clickhouse-go/v2"
	"github.com/ClickHouse/clickhouse-go/v2/lib/driver"
	"github.com/minio/minio-go/v7"
	"github.com/minio/minio-go/v7/pkg/credentials"
	opensearch "github.com/opensearch-project/opensearch-go/v2"
	"github.com/opensearch-project/opensearch-go/v2/opensearchapi"
)

// checkMinio: MakeBucket (if absent) -> PutObject -> GetObject -> compare bytes.
func checkMinio(ctx context.Context) (string, bool, error) {
	endpoint := env("MINIO_ENDPOINT")
	access := env("MINIO_ACCESS_KEY")
	secret := env("MINIO_SECRET_KEY")
	if endpoint == "" || access == "" || secret == "" {
		return "MINIO_ENDPOINT/MINIO_ACCESS_KEY/MINIO_SECRET_KEY not set", true, nil
	}
	bucket := envDefault("MINIO_BUCKET", "demo")
	secure := strings.EqualFold(env("MINIO_SECURE"), "true")

	cli, err := minio.New(endpoint, &minio.Options{
		Creds:  credentials.NewStaticV4(access, secret, ""),
		Secure: secure,
	})
	if err != nil {
		return "", false, fmt.Errorf("client: %w", err)
	}

	exists, err := cli.BucketExists(ctx, bucket)
	if err != nil {
		return "", false, fmt.Errorf("bucket-exists: %w", err)
	}
	if !exists {
		if err := cli.MakeBucket(ctx, bucket, minio.MakeBucketOptions{}); err != nil {
			return "", false, fmt.Errorf("make-bucket: %w", err)
		}
	}

	object := "flex-probe.txt"
	payload := []byte("flex-" + randHex(8))
	if _, err := cli.PutObject(ctx, bucket, object,
		bytes.NewReader(payload), int64(len(payload)),
		minio.PutObjectOptions{ContentType: "text/plain"}); err != nil {
		return "", false, fmt.Errorf("put: %w", err)
	}

	obj, err := cli.GetObject(ctx, bucket, object, minio.GetObjectOptions{})
	if err != nil {
		return "", false, fmt.Errorf("get: %w", err)
	}
	defer obj.Close()
	got, err := io.ReadAll(obj)
	if err != nil {
		return "", false, fmt.Errorf("read: %w", err)
	}
	if !bytes.Equal(got, payload) {
		return "", false, fmt.Errorf("roundtrip mismatch: put %d bytes, got %d", len(payload), len(got))
	}
	return fmt.Sprintf("bucket %q put/get roundtrip ok (%d bytes)", bucket, len(payload)), false, nil
}

// checkClickHouse: CREATE TABLE IF NOT EXISTS -> INSERT -> SELECT count() >= 1.
func checkClickHouse(ctx context.Context) (string, bool, error) {
	addr := env("CLICKHOUSE_ADDR")
	if addr == "" {
		return "CLICKHOUSE_ADDR not set", true, nil
	}
	user := envDefault("CLICKHOUSE_USER", "default")
	pass := env("CLICKHOUSE_PASSWORD")

	conn, err := clickhouse.Open(&clickhouse.Options{
		Addr: []string{addr},
		Auth: clickhouse.Auth{
			Database: envDefault("CLICKHOUSE_DATABASE", "default"),
			Username: user,
			Password: pass,
		},
		DialTimeout: 8 * time.Second,
	})
	if err != nil {
		return "", false, fmt.Errorf("open: %w", err)
	}
	defer conn.Close()

	if err := conn.Exec(ctx,
		"CREATE TABLE IF NOT EXISTS demo_flex (id UInt64, ts DateTime) ENGINE=MergeTree ORDER BY id"); err != nil {
		return "", false, fmt.Errorf("create: %w", err)
	}
	if err := conn.Exec(ctx,
		"INSERT INTO demo_flex (id, ts) VALUES (?, ?)", time.Now().UnixNano(), time.Now()); err != nil {
		return "", false, fmt.Errorf("insert: %w", err)
	}

	var count uint64
	if err := conn.QueryRow(ctx, "SELECT count() FROM demo_flex").Scan(&count); err != nil {
		return "", false, fmt.Errorf("count: %w", err)
	}
	if count < 1 {
		return "", false, fmt.Errorf("expected >=1 row, got %d", count)
	}
	// touch driver package so the import is meaningful even if unused elsewhere.
	var _ driver.Conn = conn
	return fmt.Sprintf("demo_flex has %d row(s)", count), false, nil
}

// checkOpenSearch: index a doc -> refresh -> search it back -> assert hits >= 1.
// Uses opensearch-go v2 (stable); operator TLS is self-signed so we skip verify.
func checkOpenSearch(ctx context.Context) (string, bool, error) {
	url := env("OPENSEARCH_URL")
	if url == "" {
		return "OPENSEARCH_URL not set", true, nil
	}
	user := env("OPENSEARCH_USER")
	pass := env("OPENSEARCH_PASSWORD")

	client, err := opensearch.NewClient(opensearch.Config{
		Addresses: []string{url},
		Username:  user,
		Password:  pass,
		Transport: &http.Transport{
			TLSClientConfig: &tls.Config{InsecureSkipVerify: true}, //nolint:gosec // operator self-signed TLS
		},
	})
	if err != nil {
		return "", false, fmt.Errorf("client: %w", err)
	}

	const index = "demo-flex"
	marker := randHex(8)
	doc := fmt.Sprintf(`{"msg":"flex","marker":%q,"ts":%q}`, marker, time.Now().UTC().Format(time.RFC3339))

	idxReq := opensearchapi.IndexRequest{
		Index:   index,
		Body:    strings.NewReader(doc),
		Refresh: "true", // make the doc searchable immediately (refresh step)
	}
	idxRes, err := idxReq.Do(ctx, client)
	if err != nil {
		return "", false, fmt.Errorf("index: %w", err)
	}
	defer idxRes.Body.Close()
	if idxRes.IsError() {
		return "", false, fmt.Errorf("index status: %s", idxRes.Status())
	}

	query := fmt.Sprintf(`{"query":{"match":{"marker":%q}}}`, marker)
	searchReq := opensearchapi.SearchRequest{
		Index: []string{index},
		Body:  strings.NewReader(query),
	}
	searchRes, err := searchReq.Do(ctx, client)
	if err != nil {
		return "", false, fmt.Errorf("search: %w", err)
	}
	defer searchRes.Body.Close()
	if searchRes.IsError() {
		return "", false, fmt.Errorf("search status: %s", searchRes.Status())
	}

	var parsed struct {
		Hits struct {
			Total struct {
				Value int `json:"value"`
			} `json:"total"`
		} `json:"hits"`
	}
	if err := json.NewDecoder(searchRes.Body).Decode(&parsed); err != nil {
		return "", false, fmt.Errorf("decode: %w", err)
	}
	if parsed.Hits.Total.Value < 1 {
		return "", false, fmt.Errorf("expected hits>=1, got %d", parsed.Hits.Total.Value)
	}
	return fmt.Sprintf("index %q hits=%d", index, parsed.Hits.Total.Value), false, nil
}
