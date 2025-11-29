# PostgreSQL Extensions

This directory contains Dockerfiles for building PostgreSQL extensions.

## Approach: Custom Image (Not ImageVolume)

**Decision:** We use a custom PostgreSQL image with extensions baked in.

**Why not ImageVolume?** CloudNativePG 1.27+ supports mounting extensions as OCI images via Kubernetes ImageVolume. However, this requires Kubernetes 1.33+ with the ImageVolume feature gate enabled. **EKS does not support this** - it's a managed control plane where you cannot enable API server feature gates. See "Lessons Learned" section below for details.

## Custom PostgreSQL Image: `percolationlabs/rem-pg:18`

We maintain a custom PostgreSQL 18 image with extensions baked in, available on Docker Hub:

```
percolationlabs/rem-pg:18
```

**Use this image for:**
- Kubernetes (CloudNativePG clusters)
- Local development (Docker Compose, Tilt)

## Available Extensions

### pg_net (Supabase)

Async HTTP/HTTPS networking extension. Enables PostgreSQL to make non-blocking HTTP
requests from triggers, functions, and cron jobs.

**Use cases:**
- Call external APIs from database triggers
- Webhook notifications on data changes
- Async event publishing to your API

## Building the Custom Image

### Prerequisites

- Docker with buildx enabled
- Docker Hub credentials (for pushing)

### Build and Push

```bash
cd extensions/pg_net

# Build for amd64 and push to Docker Hub
docker buildx build --platform linux/amd64 \
  -f Dockerfile.full-image \
  -t percolationlabs/rem-pg:18 \
  --push .

# For multi-arch (amd64 + arm64):
docker buildx build --platform linux/amd64,linux/arm64 \
  -f Dockerfile.full-image \
  -t percolationlabs/rem-pg:18 \
  --push .
```

## Cluster Configuration (Kubernetes)

Update your CloudNativePG Cluster spec to use the custom image:

```yaml
spec:
  # Use custom image with pg_net baked in
  imageName: percolationlabs/rem-pg:18

  postgresql:
    # pg_net requires shared_preload_libraries
    shared_preload_libraries:
      - pg_net

    # IMPORTANT: Set the database for the background worker
    parameters:
      pg_net.database_name: "remdb"  # Your application database
```

## Local Development (Docker Compose / Tilt)

Update your local postgres service to use the custom image:

```yaml
# docker-compose.yaml
services:
  postgres:
    image: percolationlabs/rem-pg:18
    environment:
      POSTGRES_PASSWORD: postgres
    command:
      - postgres
      - -c
      - shared_preload_libraries=pg_net
      - -c
      - pg_net.database_name=remdb
```

## Using pg_net

After the database is running, create the extension and use it:

```sql
-- Create the extension (run once per database)
CREATE EXTENSION IF NOT EXISTS pg_net;

-- Make an async POST request
SELECT net.http_post(
  url := 'https://your-api.example.com/webhook',
  headers := '{"Content-Type": "application/json", "Authorization": "Bearer token"}'::jsonb,
  body := '{"event": "user_created", "user_id": 123}'::jsonb
);

-- Check request status (responses are stored temporarily)
SELECT id, status_code, content::text FROM net._http_response;
```

### Trigger Example

```sql
CREATE OR REPLACE FUNCTION notify_api()
RETURNS TRIGGER AS $$
BEGIN
  PERFORM net.http_post(
    url := 'https://your-api.example.com/events',
    headers := '{"Content-Type": "application/json"}'::jsonb,
    body := jsonb_build_object(
      'table', TG_TABLE_NAME,
      'operation', TG_OP,
      'data', row_to_json(NEW)
    )
  );
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER user_changes
  AFTER INSERT OR UPDATE ON users
  FOR EACH ROW
  EXECUTE FUNCTION notify_api();
```

---

## Lessons Learned & Troubleshooting

### ImageVolume Approach (Not Available on EKS)

CloudNativePG 1.27+ supports mounting extensions as OCI images via Kubernetes ImageVolume.
However, this requires:
- Kubernetes 1.33+ with ImageVolume feature gate enabled
- PostgreSQL 18+ (for `extension_control_path` GUC)

**EKS Limitation:** EKS is a managed control plane - you cannot enable API server feature
gates like ImageVolume. Even though you can configure kubelet feature gates via Karpenter
EC2NodeClass userData, the API server feature gate is required and AWS controls that.

**Solution:** Build a custom PostgreSQL image with extensions baked in (this approach).

### libcurl Version Requirements

pg_net requires libcurl >= 7.83 for the `curl_easy_nextheader()` API.

**Problem encountered:** Building libcurl 8.x from source and linking pg_net against it
caused runtime errors:
```
epoll_ctl with CURL_POLL_REMOVE failed when receiving EPOLL_CTL_DEL for sockfd 13: Bad file descriptor
```

**Root cause:** The custom-built libcurl was missing features (we disabled zlib, brotli,
zstd, libpsl to avoid dependencies). At runtime, pg_net found the system libcurl which
had different capabilities.

**Solution:** Use the system libcurl from Debian Bookworm (7.88+) which has all required
APIs. The Dockerfile.full-image now uses `libcurl4-openssl-dev` from apt for building
and keeps `libcurl4` at runtime.

### pg_net Background Worker Configuration

The pg_net background worker runs in a specific database and polls for HTTP requests.

**Required settings:**
```yaml
postgresql:
  shared_preload_libraries:
    - pg_net
  parameters:
    pg_net.database_name: "your_database"  # MUST match where you CREATE EXTENSION
```

If `pg_net.database_name` doesn't match the database where you created the extension,
requests will queue but never execute.

### AWS Load Balancer Controller Webhook Issues

During testing, we encountered webhook TLS certificate errors:
```
failed calling webhook "mservice.elbv2.k8s.aws": x509: certificate signed by unknown authority
```

**Fix:** The webhook CA bundle in MutatingWebhookConfiguration was stale. To fix:
```bash
# Get new CA from the secret
NEW_CA=$(kubectl get secret aws-load-balancer-tls -n kube-system -o jsonpath='{.data.ca\.crt}')

# Patch all webhooks
kubectl patch mutatingwebhookconfiguration aws-load-balancer-webhook \
  --type='json' \
  -p="[
    {'op': 'replace', 'path': '/webhooks/0/clientConfig/caBundle', 'value': '$NEW_CA'},
    {'op': 'replace', 'path': '/webhooks/1/clientConfig/caBundle', 'value': '$NEW_CA'},
    {'op': 'replace', 'path': '/webhooks/2/clientConfig/caBundle', 'value': '$NEW_CA'}
  ]"
```

---

## REM Query Functions

When pg_net is available, `003_optional_extensions.sql` installs helper functions for querying the REM API directly from PostgreSQL.

### `rem_query(query, user_id)` - Async (Recommended)

Queues a REM query request and returns immediately with a request_id:

```sql
-- Fire async request to REM API
SELECT rem_query('LOOKUP sarah-chen', 'user123');
-- Returns: 1 (request_id)

-- Check result later (in a NEW transaction/session)
SELECT content::jsonb FROM net._http_response WHERE id = 1;
```

**Parameters:**
- `p_query` - REM dialect query (e.g., `LOOKUP key`, `SEARCH table 'query'`)
- `p_user_id` - User ID for query isolation
- `p_api_host` - API hostname (default: `rem-api` - works in K8s same namespace)
- `p_api_port` - API port (default: `8000`)
- `p_mode` - Query mode: `rem-dialect` or `natural-language`

### `rem_query_result(request_id, timeout_ms)` - Get Result

Retrieves the result for a completed async request. **Only works after the original transaction commits:**

```sql
-- First transaction: queue request
SELECT rem_query('LOOKUP test', 'user123');  -- Returns 5

-- Second transaction (or same session after commit): get result
SELECT rem_query_result(5, 5000);
```

### `rem_query_sync(...)` - Sync (Limited Use)

Attempts synchronous execution, but due to PostgreSQL transaction isolation, the polling loop cannot see the background worker's committed response within the same transaction.

Returns `pending` with hints if the timeout is reached:

```sql
SELECT rem_query_sync('LOOKUP test', 'user123');
-- May return: {"pending": true, "request_id": 2, "hint": "Query net._http_response..."}
```

**Note:** The async pattern with `rem_query()` is recommended for reliable operation.

---

## Completed Setup

- [x] Build custom image: `percolationlabs/rem-pg:18` (pgvector + pg_net)
- [x] Create `003_optional_extensions.sql` with try/catch
- [x] Update `postgres-cluster.yaml` and docker-compose
- [x] Test end-to-end with REM API

---

## References

- [pg_net GitHub](https://github.com/supabase/pg_net)
- [Supabase pg_net Docs](https://supabase.com/docs/guides/database/extensions/pg_net)
- [CloudNativePG ImageVolume Extensions](https://cloudnative-pg.io/documentation/current/imagevolume_extensions/)
- [libcurl Version History](https://curl.se/docs/releases.html)
