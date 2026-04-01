# SPLADE Service Deployment

SPLADE generates semantic sparse vectors for search (replaces BM25).
Runs as a separate Docker container.

## 1. Build Image

```bash
docker build -t metatron-splade-service services/splade/
docker tag metatron-splade-service ghcr.io/aisec-co-il/metatroncore:splade-service-develop
docker push ghcr.io/aisec-co-il/metatroncore:splade-service-develop
```

## 2. Deploy

Service block already in `install/docker-compose.yml`. Add to metatron-core env:

```
SPLADE_SERVICE_URL=http://splade:8080
```

Then:
```bash
docker compose pull && docker compose up -d
```

## 3. Reindex

SPLADE vectors are incompatible with BM25 — reindex required after first deploy:

```bash
curl -X POST http://SERVER:8000/api/v1/admin/reindex \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Confirm-Reindex: yes"
```

Then trigger sync from UI.

## Verify

```bash
curl http://localhost:8080/health
# {"status":"ok","model":"naver/splade-cocondenser-ensembledistil"}
```

## Resources

~600MB RAM, ~1.5GB disk. Falls back to BM25 if service unavailable.
