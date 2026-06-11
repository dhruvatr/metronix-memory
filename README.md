# Metatron Core (MTRNIX)

Open-source enterprise knowledge management system. Ingest documents from Confluence, Jira, Notion, and any MCP-compatible source. Ask questions via Telegram, Discord, or Slack — get answers grounded in your organization's real data.

## Features
- **Hybrid RAG**: Dense vectors + BM25 + knowledge graph enrichment
- **Connectors**: Confluence, Jira, Notion — native integrations with incremental sync
- **MCP Client**: Connect any tool via Model Context Protocol (`/mcp add`) — universal connector
- **Smart Search**: Query expansion, date filtering, source diversity, person detection, Jira key exact match
- **REST API**: Full API with SSE streaming, file upload, workspace management
- **Telegram Bot**: Ask questions, sync data, check status — all from Telegram
- **Discord Bot**: Same features available via Discord DMs
- **Slack Bot**: Same features available via Slack DMs
- **On-premise**: Self-hosted, your data never leaves your infrastructure
- **Multi-language**: Russian and English queries and documents

## Quick Start

### One-Line Installation

**Linux / macOS:**
```bash
curl -fsSL https://app.mtrnix.com/install.sh | bash
```

**Windows (PowerShell):**
```powershell
irm https://app.mtrnix.com/install.ps1 | iex
```

The bootstrap ensures `uv` + Python, then launches the cross-platform **setup wizard**:
preflight checks (Docker, ports, disk), guided configuration (mode, LLM provider, profile,
auto-generated secrets), and stack launch with live health status. Headless servers (over SSH)
and local machines are both supported. Re-running the wizard detects an existing install and
offers reconfigure / restart / upgrade / uninstall.

**Profiles:**
- `minimal` — backend only (Postgres, Qdrant, Neo4j, Redis, API, SPLADE, freshness worker); LLM + embeddings external.
- `full` — `minimal` + bundled Ollama, embedding-proxy, and OpenWebUI (self-contained).
- `custom` — `minimal` base plus per-service toggles.

**Non-interactive / CI:**
```bash
bash install/bootstrap.sh --config answers.yaml --non-interactive
bash install/bootstrap.sh --non-interactive --dry-run   # render .env without launching Docker
```

**Security tip:** Always verify the checksum before piping to a shell:
```bash
curl -fsSL https://raw.githubusercontent.com/openclaw/metatron/main/.sha256sum -o install.sha256
curl -fsSL https://app.mtrnix.com/install.sh -o install.sh
sha256sum -c install.sha256 && bash install.sh
```

See [Installation Guide](docs/INSTALL.md) for detailed instructions and troubleshooting.

### Manual Setup (Alternative)

**Prerequisites:**
- Docker and Docker Compose
- Python 3.12+
- Git

**Steps:**

1. **Clone and configure**
```bash
git clone https://github.com/openclaw/metatron.git
cd metatron
cp .env.example .env
# Edit .env — add your tokens and credentials
```

2. **Start infrastructure**
```bash
docker compose up -d
# Starts: PostgreSQL, Qdrant, Neo4j, Metatron, Ollama (optional)
```

3. **Install Python dependencies**
```bash
pip install -e ".[dev,channels]"
```

4. **Start the application**
```bash
python -m metatron.app
```
This starts the API server and any configured bots (Telegram, Discord, Slack).

5. **Sync data sources** (in Telegram, Discord or Slack)
```
/sync confluence
/sync jira
/sync notion
```

Or add any MCP-compatible server:
```
/mcp add my-server npx my-mcp-server
/mcp sync my-server
```

Then ask any question — the bot searches your knowledge base.

6. **Run tests**
```bash
pytest tests/unit/
# Expected: 751 tests passing
```

## Docker

There are two compose files:

| File | Purpose | What starts |
|---|---|---|
| `docker-compose.yml` | **Dev** — only databases, API runs locally | PostgreSQL, Qdrant, Neo4j |
| `docker-compose.full.yml` | **Full stack** — everything in Docker | All above + Ollama + API |

### Development (databases only)

```bash
docker compose up -d
# Then run API locally:
pip install -e ".[dev,channels]"
python -m metatron.app
```

### Full stack (everything in Docker)

```bash
docker compose -f docker-compose.full.yml up --build
```

This builds the API from source, starts all databases, and auto-pulls Ollama models (`nomic-embed-text` for embeddings, `llama3.1:8b` for chat). First run downloads ~5 GB of models.

Ports are offset to avoid conflicts with dev services:

| Service | Dev port | Full stack port |
|---|---|---|
| PostgreSQL | 5432 | 5433 |
| Qdrant | 6333 | 6335 |
| Neo4j | 7687 | 7688 |
| Ollama | 11434 | 11435 |
| API | 8000 | 8001 |

Health check: `curl http://localhost:8001/ready`

To include the UI, uncomment the `metatron-ui` service in `docker-compose.full.yml` (requires `../metatronui` directory).

## Configuration

| Variable | Required | Description |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Yes (for Telegram) | Token from @BotFather |
| `DISCORD_BOT_TOKEN` | Yes (for Discord) | Token from Discord Developer Portal |
| `SLACK_BOT_TOKEN` | Yes (for Slack) | xoxb-... from OAuth & Permissions |
| `SLACK_APP_TOKEN` | Yes (for Slack) | xapp-... from Socket Mode settings |

See `.env.example` for all configuration variables.

## Bot Commands (Telegram, Discord & Slack)
- `/start` — Greeting and capabilities
- `/search <query>` — Explicit search
- `/sync confluence|jira|notion` — Sync data source (incremental)
- `/sync confluence|jira|notion full` — Full re-sync
- `/mcp list|add|remove|sync|tools` — Manage MCP servers
- `/rebuild-aliases` — Rebuild person name registry
- `/status` — Workspace stats
- `/clear` — Clear conversation history
- `/help` — List commands

Natural language also works — just type your question. Action requests ("create a Jira ticket for...") are handled via MCP tool execution.

## Architecture
See `CLAUDE.md` for detailed architecture and `docs/TODO.md` for roadmap.

## License
Apache 2.0
