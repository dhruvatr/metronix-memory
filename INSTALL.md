# Metatron Core — Installation Guide

One-command installer for Metatron Core: hybrid RAG + agent memory infrastructure.

---

## Linux / macOS

**Prerequisites:** Docker daemon running, `curl`, bash.

```bash
# 1. Clone the branch with fixes
git clone -b fix/installer-linux-windows-fixes https://github.com/mtrnix/metatroncore.git
cd metatroncore

# 2. Run the installer
./install/bootstrap.sh
```

The wizard will ask:

| Question | Options |
|----------|---------|
| **Deployment mode** | `server` (bind 0.0.0.0, accessible from network) / `local` (bind 127.0.0.1, localhost only) |
| **LLM provider** | `ollama` / `deepseek` / `openrouter` / `custom` |
| **LLM API key** | Required for deepseek/openrouter/custom; skipped for ollama |
| **Deployment profile** | `minimal` (core + metatron-ui :3000) / `full` (everything + all UIs :3000 :3001 :3080) / `custom` (pick individual services) |
| **Integrations** | Optional: OpenAI-compat key, MCP key, Telegram token |

After startup you'll see the service table and UI endpoints.

### Non-interactive mode

```bash
./install/bootstrap.sh --non-interactive    # server + minimal + deepseek, no questions
./install/bootstrap.sh --dry-run            # generate .env, print it, don't touch Docker
./install/bootstrap.sh --config answers.yaml  # read all answers from YAML
```

`answers.yaml` example:

```yaml
mode: server
profile: full
llm_provider: deepseek
llm_api_key: sk-your-key
integrations:
  openai_compat_key: my-key
```

### Existing install — action menu

If `.env` or running containers are detected:

| Action | What it does |
|--------|-------------|
| `reconfigure` | Run wizard again, rewrite `.env`, pull images, restart stack |
| `restart` | `docker compose restart` — quick restart, no pull, keep config |
| `upgrade` | Pull fresh images, restart — keep current `.env` untouched |
| `uninstall` | Stop & remove containers (optionally delete all data volumes) |

### Post-install commands

```bash
docker compose -f install/docker-compose.yml ps        # service status
docker compose -f install/docker-compose.yml logs -f    # live logs
docker compose -f install/docker-compose.yml down       # stop containers
docker compose -f install/docker-compose.yml down --volumes  # stop + delete all data
```

---

## Windows

**Prerequisites:** Docker Desktop running (tray icon → "Engine running"), PowerShell 5.1+ (built into Windows 10+), repository cloned to drive C: (Docker Desktop shares C: by default).

```powershell
# 1. Allow script execution (one-time)
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

# 2. Clone
git clone -b fix/installer-linux-windows-fixes https://github.com/mtrnix/metatroncore.git
cd metatroncore

# 3. Run the installer
.\install\bootstrap.ps1
```

The installer will:
- Install `uv` if missing
- Create a Python venv with dependencies
- Run the same wizard as on Linux/macOS (same questions)

### If Docker is still initializing after system boot

Wait a minute and re-run:

```powershell
.\install\bootstrap.ps1
```

### Non-interactive mode

```powershell
.\install\bootstrap.ps1 -NonInteractive
.\install\bootstrap.ps1 -DryRun
.\install\bootstrap.ps1 -Config answers.yaml
```

---

## Profiles

| Profile | Services | UI Ports |
|---------|----------|----------|
| **minimal** | postgres, qdrant, neo4j, redis, splade, metatron-core, freshness-worker + metatron-ui | `:3000` |
| **full** | core + ollama, embedding-proxy, metatron-ui, metatron-ui-cc, openwebui | `:3000` `:3001` `:3080` |
| **custom** | core + pick from: ollama, embedding-proxy, openwebui, metatron-ui, metatron-ui-cc | depends on selection |

Core = always-on services: postgres, qdrant, neo4j, redis, splade, metatron-core, freshness-worker.

---

## LLM Providers

| Provider | Requires |
|----------|----------|
| `ollama` | Bundled (full profile) or external host URL (minimal profile) |
| `deepseek` | API key |
| `openrouter` | API key |
| `custom` | API key + endpoint URL |

---

## Service Ports

| Service | Port |
|---------|------|
| Metatron API | 8000 |
| Metatron UI | 3000 |
| Metatron UI CC | 3001 |
| Open WebUI | 3080 |
| Ollama | 11435 |
| PostgreSQL | 5433 |
| Qdrant HTTP | 6335 |
| Qdrant gRPC | 6336 |
| Neo4j HTTP | 7475 |
| Neo4j Bolt | 7688 |
| Redis | 6379 |
| SPLADE | 8080 |
| Embedding Proxy | 8001 |
