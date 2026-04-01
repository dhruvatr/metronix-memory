# Deploying SPLADE Sparse Vector Service

## Overview

SPLADE is a standalone microservice that generates learned sparse vectors for semantic search.
It replaces BM25 keyword-based sparse vectors with ML-powered semantic expansion
(e.g., query "car" also activates "vehicle", "automobile", "driving").

The service runs as a separate Docker container alongside metatron-core.

## Architecture

```
metatron-core (API) → HTTP POST → metatron-splade-service:8080 → sparse vector
                                  (naver/splade-cocondenser-ensembledistil, ~440MB)
```

## Prerequisites

- Docker and Docker Compose
- GitHub Container Registry access (ghcr.io/aisec-co-il/metatroncore)
- Running Metatron stack (postgres, qdrant, memgraph, ollama, metatron-core)

## Step 1: Build SPLADE Service Image

### Option A: Build locally and push

```bash
cd services/splade/

docker build -t ghcr.io/aisec-co-il/metatroncore:splade-service-develop .

docker push ghcr.io/aisec-co-il/metatroncore:splade-service-develop
```

Build takes ~3-5 minutes (downloads model at build time, ~440MB cached in image).

### Option B: Add to CI/CD

Create `.github/workflows/docker-splade.yml`:

```yaml
name: Build SPLADE Service

on:
  workflow_dispatch:

permissions:
  contents: read
  packages: write

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v4
    - uses: docker/setup-buildx-action@v3
    - uses: docker/login-action@v3
      with:
        registry: ghcr.io
        username: ${{ github.actor }}
        password: ${{ secrets.GITHUB_TOKEN }}
    - uses: docker/build-push-action@v5
      with:
        context: ./services/splade
        file: ./services/splade/Dockerfile
        push: true
        tags: ghcr.io/${{ github.repository_owner }}/metatroncore:splade-service-develop
        provenance: false
```

## Step 2: Add to Docker Compose

The service block is already in `install/docker-compose.yml`. Verify it exists:

```yaml
  splade:
    image: ghcr.io/aisec-co-il/metatroncore:splade-service-develop
    pull_policy: always
    container_name: metatron-splade-service
    ports:
      - "8080:8080"
    networks:
      - metatron_full
    healthcheck:
      test: ["CMD-SHELL", "curl -sf http://localhost:8080/health || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s
    restart: unless-stopped
```

## Step 3: Configure metatron-core

Add environment variable to `metatron-core` service:

```yaml
  metatron-core:
    environment:
      SPLADE_SERVICE_URL: http://splade:8080
    depends_on:
      splade:
        condition: service_healthy
```

Or add to the `.env` file:

```
SPLADE_SERVICE_URL=http://splade:8080
```

## Step 4: Deploy

```bash
# Pull new images
docker compose pull

# Start (splade service starts first, metatron-core waits for health check)
docker compose up -d
```

Verify SPLADE service is healthy:

```bash
docker logs metatron-splade-service --tail 5
# Should show: "Application startup complete"

curl http://localhost:8080/health
# {"status":"ok","model":"naver/splade-cocondenser-ensembledistil","device":"cpu"}
```

## Step 5: Reindex Data

SPLADE sparse vectors are incompatible with old BM25 vectors. Full reindex required.

```bash
# Get auth token
TOKEN=$(curl -s -X POST http://SERVER:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@metatron.local","password":"YOUR_PASSWORD"}' \
  | jq -r '.token')

# Trigger reindex (resets sync state + Memgraph, marks all docs for re-processing)
curl -s -X POST http://SERVER:8000/api/v1/admin/reindex \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Confirm-Reindex: yes" | jq .

# Then trigger sync from UI (Confluence first, then Jira)
```

## Verification

After sync completes, verify SPLADE is active:

1. Check metatron-core logs for `sparse.dispatch splade_enabled=True`
2. Check splade service logs for incoming requests
3. Test search — results should improve for semantic queries

## Resource Requirements

| Resource | Value |
|----------|-------|
| Memory | ~600MB (440MB model + 160MB runtime) |
| CPU | Minimal (inference ~20-50ms per text) |
| Disk | ~1.5GB (image with model cached) |
| Network | Internal Docker network only (no external access needed) |

## Troubleshooting

### SPLADE service not starting
- Check logs: `docker logs metatron-splade-service`
- Model download may fail if no internet during build — rebuild image

### metatron-core not using SPLADE
- Verify `SPLADE_SERVICE_URL` is set: check logs for `app.feature_flags splade_enabled=True`
- Check connectivity: `docker exec metatron-full-api curl http://splade:8080/health`
- If service unreachable, falls back to BM25 automatically (check logs for `splade.service.fallback_to_bm25`)

### Fallback behavior
- `SPLADE_SERVICE_URL` set + service healthy → SPLADE vectors
- `SPLADE_SERVICE_URL` set + service down → BM25 fallback (with warning log)
- `SPLADE_SERVICE_URL` empty → local model attempt → BM25 fallback
- `SPLADE_ENABLED=false` → BM25 always
