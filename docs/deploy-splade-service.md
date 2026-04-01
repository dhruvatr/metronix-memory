# SPLADE Service Deployment

SPLADE generates semantic sparse vectors for search (replaces BM25).
Runs as a separate Docker container on the same Docker network — no external ports needed.

## How it works

```
metatron-core → HTTP (internal network) → metatron-splade-service:8080 → sparse vector
```

All communication is within Docker network `metatron_full`. No ports exposed externally.
If SPLADE service is unavailable, metatron-core automatically falls back to BM25.

## Step 1: Build and push SPLADE image

```bash
docker build -t metatron-splade-service services/splade/
docker tag metatron-splade-service ghcr.io/aisec-co-il/metatroncore:splade-service-develop
docker push ghcr.io/aisec-co-il/metatroncore:splade-service-develop
```

Build takes ~3-5 min (downloads 440MB ML model, cached in image).

## Step 2: Add env variable

Add to server env file (`/usr/local/bin/.env`):

```
SPLADE_SERVICE_URL=http://splade:8080
```

`splade` is the Docker service name — resolved via internal Docker DNS.

## Step 3: Deploy

Service block is already in `install/docker-compose.yml`. Just pull and restart:

```bash
docker compose pull && docker compose up -d
```

Docker Compose will:
- Start `metatron-splade-service` container
- Connect it to `metatron_full` network
- metatron-core will wait for SPLADE health check before starting
- metatron-core reads `SPLADE_SERVICE_URL` from env and calls SPLADE via HTTP

## Step 4: Reindex

Old BM25 sparse vectors are incompatible with SPLADE. One-time reindex needed:

```bash
# Get token
TOKEN=$(curl -s -X POST http://SERVER:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@metatron.local","password":"PASSWORD"}' | jq -r '.token')

# Trigger reindex
curl -X POST http://SERVER:8000/api/v1/admin/reindex \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Confirm-Reindex: yes"
```

Then trigger sync from UI (Confluence, then Jira).

## Verify

```bash
# Check SPLADE service health (from server)
docker exec metatron-full-api curl -s http://splade:8080/health
# {"status":"ok","model":"naver/splade-cocondenser-ensembledistil","device":"cpu"}

# Check metatron-core logs for SPLADE usage
docker logs metatron-full-api | grep splade
```

## Resources

~600MB RAM, ~1.5GB disk (image with cached model).
