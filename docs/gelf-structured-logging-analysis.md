# GELF Structured Logging Analysis

**Status:** 🔍 IN PROGRESS
**Date Started:** 2025-11-25
**Goal:** Standardize log ingestion pipeline for consistent structured logging and rich Graylog dashboards

---

## Executive Summary

**Current State:**
- Graylog operational with GELF TCP input on port 12201
- Multiple log sources sending data with format inconsistencies
- Timestamp parsing errors causing indexing failures
- GELF format warnings from string timestamps instead of numeric

**Target State:**
- All log sources using proper GELF format
- Numeric Unix timestamps (epoch milliseconds)
- Structured fields for filtering and dashboards
- Zero indexing errors
- Rich contextual metadata

---

## Log Sources Inventory

### Currently Active Sources (22 Total)

| # | Source | Type | Status | Issues Found | Priority |
|---|--------|------|--------|--------------|----------|
| 1 | Fluent Bit | DaemonSet | ✅ Running | Timestamp format, connection failures | **CRITICAL** |
| 2 | Graylog | StatefulSet | ⚠️ CrashLoop | Timestamp warnings, indexing errors | **CRITICAL** |
| 3 | Traefik | DaemonSet | ✅ Running | None - excellent format | HIGH |
| 4 | ArgoCD | Deployment | ✅ Running | None | MEDIUM |
| 5 | Flux | Deployment | ✅ Running | None - perfect JSON | MEDIUM |
| 6 | Grafana | Deployment | ✅ Running | Missing dashboard directory | LOW |
| 7 | OpenSearch | StatefulSet | ✅ Running | None | MEDIUM |
| 8 | Sonarr | Deployment | ✅ Running | No indexers configured | MEDIUM |
| 9 | Alertmanager | StatefulSet | ✅ Running | Permission denied errors | LOW |
| 10 | Radarr | Deployment | ✅ Running | No indexers configured | MEDIUM |
| 11 | Prowlarr | Deployment | ✅ Running | None | MEDIUM |
| 12 | Plex | Deployment | ✅ Running | libusb_init failed | LOW |
| 13 | Jellyfin | Deployment | ✅ Running | Playlist folder missing | MEDIUM |
| 14 | Tdarr | Deployment | ✅ Running | None | LOW |
| 15 | Overseerr | Deployment | ✅ Running | No Plex admin configured | MEDIUM |
| 16 | Homepage | Deployment | ✅ Running | None | LOW |
| 17 | PostgreSQL | StatefulSet | ✅ Running | None | LOW |
| 18 | MongoDB | StatefulSet | ✅ Running | None | LOW |
| 19 | Prometheus | StatefulSet | ❌ **BROKEN** | **WAL segment file missing** | **CRITICAL** |
| 20 | External Secrets | Deployment | ⚠️ Errors | Missing 1Password keys | HIGH |
| 21 | Headlamp | Deployment | ✅ Running | None | LOW |
| 22 | Goldilocks | Deployment | ⚠️ Errors | VPA workload matching failures | MEDIUM |

### Analysis Status

- [x] Inventory complete
- [x] Sample logs collected
- [x] Format issues identified
- [ ] Transformation rules designed
- [ ] Fluent Bit configuration updated
- [ ] Testing completed
- [ ] Dashboards created

---

## Raw Log Samples by Source

### 1. Fluent Bit (Log Collector) - observability namespace

**Pod:** `fluent-bit-vgxcc`
**Issues:** Connection errors to Graylog, GELF output failures

```
[2025/11/25 19:56:08] [error] [output:gelf:gelf.0] no upstream connections available
[2025/11/25 19:56:08] [error] [engine] chunk '1-1764100547.244938481.flb' cannot be retried: task_id=7, input=tail.0 > output=gelf.0
[2025/11/25 19:56:08] [ warn] [engine] failed to flush chunk '1-1764100556.244608804.flb', retry in 11 seconds: task_id=40, input=tail.0 > output=gelf.0 (out_id=0)
[2025/11/25 19:56:08] [error] [net] TCP connection failed: graylog-web.observability.svc.cluster.local:12201 (Connection refused)
```

**Analysis:**
- Fluent Bit unable to connect when Graylog crashes
- Chunks being dropped due to retry limits
- Connection target: `graylog-web.observability.svc.cluster.local:12201`

### 2. Graylog (Log Management) - observability namespace

**Pod:** `graylog-0`
**Issues:** Invalid timestamp format warnings, OpenSearch indexing errors

```
2025-11-25 19:54:58,217 WARN    [GelfDecoder] - GELF message <9ef1ee41-ca38-11f0-a371-aea097d55863> (received from <10.244.1.25:48360>) has invalid "timestamp": 2025-11-25T19:54:57.49464557Z  (type: STRING) - {}
2025-11-25 19:54:58,224 WARN    [GelfDecoder] - GELF message <9ef1ee42-ca38-11f0-a371-aea097d55863> (received from <10.244.1.25:48346>) has invalid "timestamp": 2025-11-25T19:54:57.492163344Z  (type: STRING) - {}
2025-11-25 19:55:19,775 ERROR   [ChunkedBulkIndexer] - Failed to index [6] messages. Please check the index error log in your web interface for the reason. Error: failure in bulk execution:
```

**Analysis:**
- **CRITICAL**: Timestamp arriving as ISO8601 string (`2025-11-25T19:54:57.49464557Z`)
- GELF spec requires numeric Unix timestamp
- Graylog accepts messages but logs warnings
- OpenSearch rejects messages with indexing errors

### 3. Traefik (Ingress Controller) - traefik namespace

**Pod:** `traefik-xzn5w`
**Format:** Combined Log Format (CLF) with extensions

```
192.168.1.85 - - [25/Nov/2025:19:58:27 +0000] "GET /api/streams HTTP/1.1" 200 410 "-" "-" 87155 "observability-graylog-96977e7e1cc14de425c0@kubernetescrd" "http://10.244.1.26:9000" 1050ms
192.168.1.85 - - [25/Nov/2025:19:58:27 +0000] "POST /api/views/search/69260a615511247242662a2d/execute HTTP/1.1" 201 259 "-" "-" 87159 "observability-graylog-96977e7e1cc14de425c0@kubernetescrd" "http://10.244.1.26:9000" 703ms
192.168.1.85 - - [25/Nov/2025:19:58:28 +0000] "POST /api/cluster/metrics/multiple HTTP/1.1" 200 295 "-" "-" 87160 "observability-graylog-96977e7e1cc14de425c0@kubernetescrd" "http://10.244.1.26:9000" 198ms
```

**Fields Present:**
- `192.168.1.85` - Client IP
- `[25/Nov/2025:19:58:27 +0000]` - Timestamp
- `"GET /api/streams HTTP/1.1"` - Request method, path, protocol
- `200` - HTTP status code
- `410` - Response size (bytes)
- `87155` - Request ID
- `"observability-graylog-...@kubernetescrd"` - Backend service
- `"http://10.244.1.26:9000"` - Upstream URL
- `1050ms` - Response time

**Analysis:**
- Structured format, excellent for parsing
- Contains all key HTTP metrics for dashboards
- Need regex parser to extract fields
- **Priority:** HIGH - Critical for infrastructure monitoring

### 4. ArgoCD (GitOps Controller) - argocd namespace

**Pod:** `argocd-server-c4d9755f7-8k7k5`
**Format:** Logrus structured logging (key=value pairs)

```
time="2025-11-25T19:43:41Z" level=info msg="invalidated cache for resource in namespace: argocd with the name: argocd-notifications-secret"
time="2025-11-25T19:45:54Z" level=info msg="invalidated cache for resource in namespace: argocd with the name: argocd-notifications-cm"
time="2025-11-25T19:52:54Z" level=info msg="Alloc=13814 TotalAlloc=520870 Sys=43350 NumGC=1313 Goroutines=151"
```

**Fields Present:**
- `time` - ISO8601 timestamp
- `level` - Log level (info, warn, error)
- `msg` - Message text

**Analysis:**
- Already structured (key=value format)
- Easy to parse with regex
- Log level clearly identified
- **Priority:** MEDIUM - Important for GitOps monitoring

### 5. Flux (GitOps Controller) - flux-system namespace

**Pod:** `source-controller-7b565f499f-2smw4`
**Format:** Structured JSON

```json
{"level":"info","ts":"2025-11-25T19:54:27.364Z","msg":"no changes since last reconcilation: observed revision 'main@sha1:dd0b6b71c12fcccfdec07cb15f7c410b4aa6750c'","controller":"gitrepository","controllerGroup":"source.toolkit.fluxcd.io","controllerKind":"GitRepository","GitRepository":{"name":"flux-system","namespace":"flux-system"},"namespace":"flux-system","name":"flux-system","reconcileID":"4880255a-4f54-41af-9bdd-da2a8fe64a02"}
```

**Fields Present:**
- `level` - Log level
- `ts` - ISO8601 timestamp
- `msg` - Message
- `controller`, `controllerGroup`, `controllerKind` - Controller metadata
- `GitRepository` - Resource details
- `namespace`, `name` - Resource identifiers
- `reconcileID` - Unique reconciliation ID

**Analysis:**
- **EXCELLENT**: Already JSON structured
- Fluent Bit can parse with `Merge_Log On`
- Rich metadata for filtering
- **Priority:** MEDIUM - Important for infrastructure monitoring

### 6. Grafana (Visualization) - monitoring namespace

**Pod:** `kube-prometheus-stack-grafana-5dd5dd4dc7-k6pfb`
**Container:** `grafana`
**Format:** Logrus structured (key=value)

```
logger=provisioning.dashboard type=file name=default t=2025-11-25T19:58:28.484267626Z level=error msg="failed to search for dashboards" error="stat /var/lib/grafana/dashboards/default: no such file or directory"
logger=context userId=0 orgId=0 uname= t=2025-11-25T19:58:30.38046043Z level=info msg="Request Completed" method=GET path=/ status=302 remote_addr=10.244.1.212 time_ms=0 duration=160.35µs size=29 referer= handler=/ status_source=server
```

**Fields Present:**
- `logger` - Logger name (context, provisioning.dashboard)
- `type`, `name` - Dashboard provisioner details
- `t` - ISO8601 timestamp with nanoseconds
- `level` - Log level
- `msg` - Message
- `error` - Error details (when present)
- HTTP request fields: `method`, `path`, `status`, `remote_addr`, `time_ms`, `duration`, `size`

**Analysis:**
- Mix of structured and semi-structured
- HTTP access logs are excellent for dashboards
- Error logs about missing dashboard directory (needs fix)
- **Priority:** LOW - Not critical, but useful

### 7. OpenSearch (Search/Analytics) - observability namespace

**Pod:** `opensearch-cluster-master-0`
**Container:** `opensearch`
**Format:** Log4j pattern

```
[2025-11-25T19:46:02,816][INFO ][o.o.j.s.JobSweeper       ] [opensearch-cluster-master-0] Running full sweep
[2025-11-25T19:51:02,816][INFO ][o.o.j.s.JobSweeper       ] [opensearch-cluster-master-0] Running full sweep
[2025-11-25T19:56:03,681][INFO ][o.o.s.s.c.FlintStreamingJobHouseKeeperTask] [opensearch-cluster-master-0] Starting housekeeping task for auto refresh streaming jobs.
```

**Fields Present:**
- `[2025-11-25T19:46:02,816]` - Timestamp with milliseconds
- `[INFO]` - Log level
- `[o.o.j.s.JobSweeper]` - Logger class (abbreviated)
- `[opensearch-cluster-master-0]` - Node name
- Message text

**Analysis:**
- Java logging format
- Structured with clear delimiters
- Relatively low volume (housekeeping messages)
- **Priority:** MEDIUM - Important for observability stack health

### 8. Sonarr (Media Automation) - media-prod namespace

**Pod:** `sonarr-6596c75b97-jk6v5`
**Container:** `sonarr`
**Format:** Custom bracketed format

```
[Info] DownloadDecisionMaker: No results found
[Info] RssSyncService: RSS Sync Completed. Reports found: 0, Reports grabbed: 0
[Info] RssSyncService: Starting RSS Sync
[Warn] FetchAndParseRssService: No available indexers. check your configuration.
[Info] DownloadDecisionMaker: No results found
```

**Fields Present:**
- `[Info]`, `[Warn]` - Log level
- Class/Service name: `DownloadDecisionMaker`, `RssSyncService`, `FetchAndParseRssService`
- Message text with structured data (Reports found: X, Reports grabbed: Y)

**Analysis:**
- Simple structured format
- Log level easy to extract
- Contains application-specific metrics
- **Priority:** MEDIUM - Useful for arr-stack monitoring
- **Note:** Same format for Radarr, Prowlarr, Readarr

### 9. Alertmanager (Alerting) - monitoring namespace

**Pod:** `alertmanager-kube-prometheus-stack-alertmanager-0`
**Container:** `alertmanager`
**Format:** Logrus structured (key=value)

```
ts=2025-11-25T18:51:03.259Z caller=silence.go:432 level=info component=silences msg="Running maintenance failed" err="open /alertmanager/silences.375dd0a85f3c08b3: permission denied"
ts=2025-11-25T18:51:03.260Z caller=nflog.go:352 level=error component=nflog msg="Running maintenance failed" err="open /alertmanager/nflog.e8010f8a413c488: permission denied"
```

**Fields Present:**
- `ts` - ISO8601 timestamp
- `caller` - Source file and line
- `level` - Log level
- `component` - Component name
- `msg` - Message
- `err` - Error details

**Analysis:**
- Well-structured key=value format
- **Issue Found:** Permission denied errors (persistent)
- Storage permissions problem (needs investigation)
- **Priority:** LOW - Not critical but needs fix

### 10. Radarr (Movie Management) - media-prod namespace

**Pod:** `radarr-65759684f6-bzvwf`
**Container:** `radarr`
**Format:** Custom bracketed format (identical to Sonarr)

```
[Info] DownloadDecisionMaker: No results found
[Info] RssSyncService: RSS Sync Completed. Reports found: 0, Reports grabbed: 0
[Info] RssSyncService: Starting RSS Sync
[Warn] FetchAndParseRssService: No available indexers. check your configuration.
[Info] DownloadDecisionMaker: No results found
[Info] RssSyncService: RSS Sync Completed. Reports found: 0, Reports grabbed: 0
```

**Analysis:**
- Identical format to Sonarr (same *arr application family)
- Same indexer configuration warning
- **Priority:** MEDIUM

### 11. Prowlarr (Indexer Manager) - media-prod namespace

**Pod:** `prowlarr-6c84594c5b-g5zzz`
**Container:** `prowlarr`
**Format:** Structured key=value with component identification

```
[Info] FluentMigrator.Runner.MigrationRunner: => 0.0175364s
[Info] Microsoft.Hosting.Lifetime: Now listening on: http://[::]:9696
[Info] UpdaterConfigProvider: Update mechanism BuiltIn not supported in the current configuration, changing to Docker.
[Info] AppSyncProfileService: Setting up default app profile
[ls.io-init] done.
[Info] CommandExecutor: Starting 3 threads for tasks.
[Info] ManagedHttpDispatcher: IPv4 is available: True, IPv6 will be disabled
[Info] Microsoft.Hosting.Lifetime: Application started. Press Ctrl+C to shut down.
[Info] Microsoft.Hosting.Lifetime: Hosting environment: Production
[Info] Microsoft.Hosting.Lifetime: Content root path: /app/prowlarr/bin
```

**Analysis:**
- ASP.NET Core application with .NET logging
- More detailed startup logs than Sonarr/Radarr
- Component/class names in logs (FluentMigrator, Microsoft.Hosting)
- **Priority:** MEDIUM

### 12. Plex (Media Server) - media-prod namespace

**Pod:** `plex-658bb8d74d-9kgtt`
**Format:** Sentry crash reporter options (stderr output)

```
  --device arg           Device string
  --model arg            Device model string
  --allowRetries arg     Whether we will allow retries

Session Health options:
  --sessionStatus arg    Seassion health status (exited, crashed, or abnormal)
  --sessionStart arg     Session start timestamp in UTC or epoch time
  --sessionDuration arg  Session duration in seconds

Common options:
  --userId arg           User that owns this product
  --version arg          Version of the product
  --sentryUrl arg        Sentry URL to upload to
  --sentryKey arg        Sentry Key for the project
Critical: libusb_init failed
```

**Analysis:**
- Showing Sentry crash reporter help output (unusual)
- **Error:** `libusb_init failed` - USB library initialization failure
- Not actual application logs, stderr output
- **Priority:** LOW - Not affecting core functionality

### 13. Jellyfin (Media Server) - media-prod namespace

**Pod:** `jellyfin-6b87cbf579-qk9zp`
**Format:** ASP.NET Core structured logging with timestamps

```
[08:14:23] [WRN] [3] Microsoft.EntityFrameworkCore.Query: The query uses a row limiting operator ('Skip'/'Take') without an 'OrderBy' operator. This may lead to unpredictable results.
[08:14:23] [INF] [3] Emby.Server.Implementations.ScheduledTasks.TaskManager: Refresh People Completed after 0 minute(s) and 0 seconds
[08:14:23] [WRN] [22] MediaBrowser.Controller.Entities.BaseItem: Library folder /config/data/data/playlists is inaccessible or empty, skipping
[08:14:23] [INF] [3] Emby.Server.Implementations.ScheduledTasks.TaskManager: TasksRefreshChannels Completed after 0 minute(s) and 0 seconds
[09:14:23] [INF] [4] Emby.Server.Implementations.Library.LibraryManager: Validating media library
[09:14:27] [INF] [16] Jellyfin.LiveTv.Guide.GuideManager: Refreshing guide with 7 days of guide data
```

**Fields Present:**
- `[08:14:23]` - Timestamp (HH:MM:SS)
- `[WRN]`/`[INF]` - Log level
- `[3]` - Thread ID
- Component/class name
- Message with task timing

**Analysis:**
- Excellent structured format
- **Warning:** Playlist folder inaccessible (persistent)
- **Warning:** Query without OrderBy operator
- Rich metadata (thread IDs, timing, component names)
- **Priority:** MEDIUM

### 14. Tdarr (Media Transcoding) - media-prod namespace

**Pod:** `tdarr-6fcc75c99-kq8rz`
**Container:** `tdarr`
**Format:** JSON-formatted with ANSI color codes

```
[32m[2025-11-25T10:21:04.554] [INFO] Tdarr_Server[39m - Updating plugins
[32m[2025-11-25T10:21:04.953] [INFO] Tdarr_Server[39m - [Plugin Update] Starting
[32m[2025-11-25T10:21:05.445] [INFO] Tdarr_Server[39m - [Plugin Update] Plugin repo has not changed, skipping update
[32m[2025-11-25T10:21:06.420] [INFO] Tdarr_Node[39m - Downloading plugins from server
[32m[2025-11-25T10:21:07.185] [INFO] Tdarr_Node[39m - Finished downloading plugins from server
```

**Fields Present:**
- `[32m` - ANSI color code (green)
- `[2025-11-25T10:21:04.554]` - ISO8601 timestamp with milliseconds
- `[INFO]` - Log level
- `Tdarr_Server`/`Tdarr_Node` - Component
- Message text

**Analysis:**
- Dual-role container (Server + Node in same pod)
- ANSI color codes present (terminal output captured)
- Clean INFO-only logs, no errors
- **Priority:** LOW

### 15. Overseerr (Request Management) - media-prod namespace

**Pod:** `overseerr-74d4979f85-ps277`
**Format:** Winston structured logging with ANSI colors

```
2025-11-25T20:00:00.008Z [[32minfo[39m][Jobs]: Starting scheduled job: Plex Watchlist Sync
2025-11-25T20:00:00.013Z [[32minfo[39m][Jobs]: Starting scheduled job: Plex Recently Added Scan
2025-11-25T20:00:00.014Z [[32minfo[39m][Plex Scan]: Scan starting {"sessionId":"28880b99-6020-4979-a152-9ecedf819ccf"}
2025-11-25T20:00:00.017Z [[33mwarn[39m][Plex Scan]: No admin configured. Plex scan skipped.
2025-11-25T20:01:00.006Z [[34mdebug[39m][Jobs]: Starting scheduled job: Download Sync
```

**Fields Present:**
- ISO8601 timestamp with milliseconds
- ANSI color-coded log levels (`[32minfo[39m`, `[33mwarn[39m`, `[34mdebug[39m`)
- Component in brackets (`[Jobs]`, `[Plex Scan]`)
- Structured data (JSON sessionId)

**Analysis:**
- **Warning:** No Plex admin configured (scan skipped)
- Node.js Winston logger
- ANSI colors for terminal output
- **Priority:** MEDIUM

### 16. Homepage (Dashboard) - media-prod namespace

**Pod:** `homepage-79f7c5cc6c-zrzdv`
**Format:** Next.js console output

```
/app/config already owned by correct UID/GID, skipping chown
/app/.next already owned by correct UID/GID or running as root, skipping chown
   ▲ Next.js 15.5.2
   - Local:        http://localhost:3000
   - Network:      http://0.0.0.0:3000

 ✓ Starting...
 ✓ Ready in 8.7s
```

**Analysis:**
- Minimal logging (startup only)
- Next.js 15.5.2 application
- Ready in 8.7 seconds
- **Priority:** LOW

### 17. PostgreSQL (Arr-Stack Database) - media-prod namespace

**Pod:** `postgresql-79674c689-nmml5`
**Format:** PostgreSQL standard text logs

```
2025-11-25 19:19:16.514 UTC [56] LOG:  checkpoint starting: time
2025-11-25 19:19:19.728 UTC [56] LOG:  checkpoint complete: wrote 33 buffers (0.2%); 0 WAL file(s) added, 0 removed, 0 recycled; write=3.211 s, sync=0.002 s, total=3.215 s
2025-11-25 19:24:16.823 UTC [56] LOG:  checkpoint starting: time
2025-11-25 19:24:49.047 UTC [56] LOG:  checkpoint complete: wrote 322 buffers (2.0%); 0 WAL file(s) added, 0 removed, 0 recycled; write=32.217 s, sync=0.005 s, total=32.224 s
```

**Fields Present:**
- `2025-11-25 19:19:16.514 UTC` - Timestamp with milliseconds
- `[56]` - Process ID
- `LOG` - Log level
- Detailed checkpoint metrics

**Analysis:**
- Standard PostgreSQL format
- Regular checkpoint operations (every 5 minutes)
- No errors detected
- **Priority:** LOW

### 18. MongoDB (Graylog Database) - observability namespace

**Pod:** `mongodb-5f58dfdb96-wvdcv`
**Format:** MongoDB JSON structured logging

```json
{"t":{"$date":"2025-11-25T20:07:51.575+00:00"},"s":"I","c":"NETWORK","id":22943,"ctx":"listener","msg":"Connection accepted","attr":{"remote":"127.0.0.1:52862","connectionId":107434,"connectionCount":5}}
{"t":{"$date":"2025-11-25T20:07:51.582+00:00"},"s":"I","c":"NETWORK","id":51800,"ctx":"conn107434","msg":"client metadata","attr":{"client":"conn107434","doc":{"application":{"name":"mongosh 2.5.9"}}}}
{"t":{"$date":"2025-11-25T20:07:51.584+00:00"},"s":"I","c":"ACCESS","id":10483900,"ctx":"conn107434","msg":"Connection not authenticating"}
```

**Fields Present:**
- `t.$date` - ISO8601 timestamp
- `s` - Severity (I=Info)
- `c` - Component (NETWORK, ACCESS, WTCHKPT)
- `id` - Message ID
- `ctx` - Context
- `msg` - Message
- `attr` - Attributes (structured)

**Analysis:**
- **EXCELLENT:** Modern MongoDB JSON logging
- No authentication configured (expected for internal)
- Health check connections from mongosh
- **Priority:** LOW

### 19. Prometheus (Metrics) - monitoring namespace

**Pod:** `prometheus-kube-prometheus-stack-prometheus-0`
**Format:** Prometheus structured key=value

```
ts=2025-11-25T20:07:49.532Z caller=group.go:553 level=warn component="rule manager" msg="Rule sample appending failed" err="write to WAL: log samples: create new segment file: open /prometheus/wal/00000020: no such file or directory"
ts=2025-11-25T20:07:51.458Z caller=scrape.go:1357 level=error component="scrape manager" msg="Scrape commit failed" err="write to WAL: log samples: create new segment file: open /prometheus/wal/00000020: no such file or directory"
```

**Analysis:**
- **CRITICAL ISSUE:** WAL (Write-Ahead Log) segment file missing
- Cannot write metrics samples
- Affects rule manager AND scrape manager
- Cascading failures across entire monitoring stack
- **Priority:** CRITICAL - Prometheus not functioning

### 20. External Secrets Operator - external-secrets namespace

**Pod:** `external-secrets-75659c847f-hwxz7`
**Format:** JSON structured (controller-runtime)

```json
{"level":"error","ts":1763939517.2580407,"msg":"Reconciler error","controller":"secretstore","error":"could not validate provider: Get \"http://onepassword-connect:8080/v1/vaults\": dial tcp: connect: connection refused"}
{"level":"error","ts":1763951740.6663632,"msg":"Reconciler error","controller":"externalsecret","error":"key not found in 1Password Vaults: flux-discord-webhook in: map[catalyst-eso:1]"}
{"level":"info","ts":1764083644.2056758,"msg":"reconciled secret","ExternalSecret":{"name":"homepage-secrets","namespace":"media-prod"}}
```

**Analysis:**
- **Issue:** 1Password Connect connection refused
- **Issue:** Missing key `flux-discord-webhook` in vault
- Eventually reconciles successfully
- **Priority:** HIGH - Missing secrets causing errors

### 21. Headlamp (Kubernetes UI) - infra-testing namespace

**Pod:** `headlamp-7c876546f7-ggqgq`
**Format:** JSON structured with request metrics

```json
{"level":"info","duration_ms":"6.14","source":"/headlamp/backend/cmd/headlamp.go","line":1483,"time":"2025-11-25T20:04:24Z","message":"Request completed successfully"}
{"level":"info","duration_ms":"278.08","source":"/headlamp/backend/cmd/headlamp.go","line":1483,"time":"2025-11-25T20:05:24Z","message":"Request completed successfully"}
```

**Analysis:**
- Clean request logging with duration metrics
- Response times: 2-348ms
- **Priority:** LOW

### 22. Goldilocks Dashboard (Resource Recommendations) - infra-testing namespace

**Pod:** `goldilocks-dashboard-558988b8b5-wxrz9`
**Format:** Go error logs

```
E1124 05:33:43.456523       1 summary.go:162] no matching Workloads found for VPA/goldilocks-nfs-subdir-external-provisioner
E1124 05:33:43.458766       1 templates.go:114] Error writing template: write tcp: broken pipe
```

**Analysis:**
- **Issue:** VPA workload matching failures
- **Issue:** Network disconnections (broken pipe)
- Cannot generate recommendations
- **Priority:** MEDIUM

---

## Known Issues

### Issue 1: OpenSearch Timestamp Parsing Errors

**Error:**
```
ERROR [ChunkedBulkIndexer] - Failed to index [1] messages
mapper_parsing_exception: failed to parse field [ts] of type [date]
Preview of field's value: '1.764099672486776E9'
```

**Root Cause:**
- Timestamps sent in scientific notation (`1.764E9`)
- OpenSearch expects epoch milliseconds as integer
- Likely coming from Fluent Bit transformation

**Impact:**
- Some messages fail to index
- Data loss for affected logs
- Gaps in log timeline

**Solution:**
- Update Fluent Bit timestamp format
- Ensure numeric epoch milliseconds (not scientific notation)
- Add field type validation

### Issue 2: GELF Invalid Timestamp Format

**Warning:**
```
WARN [GelfDecoder] - GELF message has invalid "timestamp": 2025-11-25T19:40:47.493771618Z (type: STRING)
```

**Root Cause:**
- GELF spec requires numeric Unix timestamp (seconds or milliseconds)
- Logs arriving with ISO8601 string format
- Graylog accepts but logs warnings

**Impact:**
- Warning noise in Graylog logs
- Potential performance overhead from parsing
- Inconsistent timestamp handling

**Solution:**
- Convert ISO8601 to Unix epoch in Fluent Bit
- Use numeric timestamp field
- Remove string timestamp field

---

## Log Source Analysis

### 1. Fluent Bit (Log Collector)

**Current Configuration:** TBD - Need to inspect ConfigMap

**Sample Messages:** TBD - Need to capture

**Identified Issues:**
- Timestamp in scientific notation
- String timestamps in ISO8601 format

**Required Transformations:**
- [ ] Convert timestamps to numeric epoch milliseconds
- [ ] Add Kubernetes metadata (namespace, pod, container)
- [ ] Add log level field
- [ ] Structure application logs (JSON parsing)
- [ ] Add source tagging

**Target GELF Format:**
```json
{
  "version": "1.1",
  "host": "pod-name",
  "short_message": "Log message text",
  "timestamp": 1732565999.123,
  "level": 6,
  "_namespace": "observability",
  "_pod": "pod-name",
  "_container": "container-name",
  "_node": "talos00",
  "_log_level": "INFO",
  "_app": "application-name"
}
```

### 2. Traefik (Ingress Controller)

**Current Configuration:** TBD

**Sample Messages:** TBD

**Expected Fields:**
- Request method, path, status
- Response time, size
- Client IP, user agent
- Backend service
- TLS version

**Required Transformations:**
- [ ] Parse access logs
- [ ] Extract structured fields
- [ ] Add request/response metadata

**Target GELF Format:**
```json
{
  "short_message": "GET /api/health 200",
  "_http_method": "GET",
  "_http_path": "/api/health",
  "_http_status": 200,
  "_http_response_time_ms": 12,
  "_http_response_bytes": 1024,
  "_http_client_ip": "192.168.1.100",
  "_http_user_agent": "curl/7.88.1",
  "_backend_service": "graylog",
  "_tls_version": "TLSv1.3"
}
```

### 3. ArgoCD (GitOps Controller)

**Current Configuration:** TBD

**Sample Messages:** TBD

**Expected Fields:**
- Application name
- Sync status
- Repo URL, branch
- Kubernetes resource details

**Required Transformations:**
- [ ] Parse structured JSON logs
- [ ] Extract ArgoCD-specific metadata
- [ ] Add sync status fields

### 4. Arr-Stack Applications

**Components:**
- Sonarr, Radarr, Prowlarr (same logging format)
- Plex, Jellyfin, Tdarr

**Current Configuration:** TBD

**Sample Messages:** TBD

**Expected Fields:**
- Application name
- Log level
- Event type (download, import, etc.)
- Media metadata (title, quality)

**Required Transformations:**
- [ ] Parse application-specific formats
- [ ] Extract media metadata
- [ ] Normalize log levels

---

## Fluent Bit Configuration Strategy

### Current State
```bash
# Need to inspect current Fluent Bit setup
kubectl get configmap -n observability
kubectl get daemonset -n observability
```

### Target Configuration

**Input:** Tail Kubernetes logs
**Filters:**
1. Kubernetes metadata enrichment
2. JSON parsing (for structured app logs)
3. Timestamp normalization
4. Field extraction and mapping
5. Log level normalization

**Output:** GELF TCP to Graylog

**Example Configuration:**
```ini
[INPUT]
    Name              tail
    Path              /var/log/containers/*.log
    Parser            cri
    Tag               kube.*
    Refresh_Interval  5
    Mem_Buf_Limit     5MB
    Skip_Long_Lines   On

[FILTER]
    Name                kubernetes
    Match               kube.*
    Kube_URL            https://kubernetes.default.svc:443
    Kube_CA_File        /var/run/secrets/kubernetes.io/serviceaccount/ca.crt
    Kube_Token_File     /var/run/secrets/kubernetes.io/serviceaccount/token
    Kube_Tag_Prefix     kube.var.log.containers.
    Merge_Log           On
    Keep_Log            Off
    K8S-Logging.Parser  On
    K8S-Logging.Exclude On

[FILTER]
    Name    modify
    Match   *
    # Convert timestamp to numeric epoch (seconds with decimals)
    Add     timestamp ${TIMESTAMP}

[FILTER]
    Name    lua
    Match   *
    script  /fluent-bit/scripts/gelf-transform.lua
    call    transform_to_gelf

[OUTPUT]
    Name          gelf
    Match         *
    Host          graylog
    Port          12201
    Mode          tcp
    Gelf_Short_Message_Key log
    Gelf_Timestamp_Key timestamp
    Gelf_Host_Key host
    Gelf_Full_Message_Key message
```

**Lua Script for Transformations:**
```lua
function transform_to_gelf(tag, timestamp, record)
    -- Convert timestamp to numeric seconds.microseconds
    record["timestamp"] = timestamp

    -- Set host field
    record["host"] = record["kubernetes"]["pod_name"]

    -- Extract log level from message
    local level_map = {
        FATAL = 2,
        ERROR = 3,
        WARN = 4,
        INFO = 6,
        DEBUG = 7,
        TRACE = 7
    }

    for level_name, level_num in pairs(level_map) do
        if string.match(record["log"], level_name) then
            record["level"] = level_num
            record["_log_level"] = level_name
            break
        end
    end

    -- Add Kubernetes metadata as GELF fields
    record["_namespace"] = record["kubernetes"]["namespace_name"]
    record["_pod"] = record["kubernetes"]["pod_name"]
    record["_container"] = record["kubernetes"]["container_name"]
    record["_node"] = record["kubernetes"]["host"]
    record["_app"] = record["kubernetes"]["labels"]["app"]

    return 2, timestamp, record
end
```

---

## Dashboard Requirements

### 1. Infrastructure Overview Dashboard

**Panels:**
- Log rate by namespace (line chart)
- Log level distribution (pie chart)
- Top 10 error-generating pods (bar chart)
- Recent errors (table)
- Log volume by application (stacked area)

**Filters:**
- Namespace selector
- Time range
- Log level
- Pod/container selector

### 2. Traefik Access Dashboard

**Panels:**
- Request rate (line chart)
- Status code distribution (pie chart)
- Response time percentiles (line chart)
- Top URLs by traffic (table)
- Top clients by request count (table)
- Error rate by backend (bar chart)

**Filters:**
- Backend service
- HTTP status code
- Client IP
- Time range

### 3. Application-Specific Dashboards

**Per Application:**
- Error rate trend
- Log level distribution
- Recent errors with context
- Performance metrics (from logs)
- Event timeline

---

## Implementation Plan

### Phase 1: Audit & Analysis (CURRENT)

**Tasks:**
- [x] Create tracking document
- [ ] Inventory all log sources
- [ ] Collect sample logs from each source
- [ ] Identify format issues
- [ ] Document current Fluent Bit configuration

**Deliverables:**
- Complete log source inventory
- Sample log collection
- Format issue documentation

### Phase 2: Fluent Bit Configuration

**Tasks:**
- [ ] Design transformation rules
- [ ] Write Lua scripts for complex transformations
- [ ] Update Fluent Bit ConfigMap
- [ ] Deploy and test configuration
- [ ] Verify zero indexing errors

**Deliverables:**
- Updated Fluent Bit configuration
- Transformation scripts
- Test results

### Phase 3: Dashboard Creation

**Tasks:**
- [ ] Create Infrastructure Overview dashboard
- [ ] Create Traefik Access dashboard
- [ ] Create Application-specific dashboards
- [ ] Export dashboard JSON
- [ ] Add dashboards to infrastructure repo

**Deliverables:**
- Dashboard JSON files
- Dashboard documentation
- Screenshot gallery

### Phase 4: Validation & Optimization

**Tasks:**
- [ ] Verify all logs indexing correctly
- [ ] Performance testing (log throughput)
- [ ] Dashboard usability testing
- [ ] Optimize field extraction
- [ ] Document best practices

**Deliverables:**
- Validation report
- Performance metrics
- Best practices documentation

---

## Success Metrics

- **Zero indexing errors** in Graylog
- **Zero GELF format warnings**
- **100% timestamp accuracy** (numeric epoch)
- **Structured fields** in 90%+ of logs
- **Dashboard response time** < 2 seconds
- **Log throughput** handles cluster load

---

## GELF Specification Reference

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `version` | string | GELF spec version (1.1) |
| `host` | string | Originating host/pod |
| `short_message` | string | Short message (required) |
| `timestamp` | number | Unix timestamp (seconds.microseconds) |

### Optional Fields

| Field | Type | Description |
|-------|------|-------------|
| `full_message` | string | Full message with backtrace |
| `level` | number | Syslog severity (0-7) |
| `facility` | string | Facility name |
| `line` | number | Line number |
| `file` | string | Source file |

### Custom Fields

- Prefix with underscore: `_custom_field`
- No restrictions on naming or types
- Used for filtering and dashboards

### Syslog Severity Levels

| Level | Name | Description |
|-------|------|-------------|
| 0 | Emergency | System unusable |
| 1 | Alert | Action must be taken immediately |
| 2 | Critical | Critical conditions |
| 3 | Error | Error conditions |
| 4 | Warning | Warning conditions |
| 5 | Notice | Normal but significant |
| 6 | Informational | Informational messages |
| 7 | Debug | Debug-level messages |

---

## Next Steps

1. **Collect log samples** from all active sources
2. **Inspect Fluent Bit** current configuration
3. **Design transformations** for each log source
4. **Implement and test** configuration changes
5. **Create dashboards** for monitoring
6. **Document** configuration and best practices

---

## Notes

- Graylog supports multiple inputs - can add UDP/HTTP if needed
- Consider log rotation/retention policies
- Monitor Graylog resource usage as log volume increases
- Plan for index optimization strategy
- Consider alerting rules for critical errors

---

## References

- GELF Specification: https://go2docs.graylog.org/current/getting_in_log_data/gelf.html
- Fluent Bit Documentation: https://docs.fluentbit.io/
- Graylog Documentation: https://go2docs.graylog.org/
- Kubernetes Logging Best Practices: https://kubernetes.io/docs/concepts/cluster-administration/logging/
