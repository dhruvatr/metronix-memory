# Metatron Core (MTRNIX)

Open-source enterprise knowledge management system. Ingest documents from Confluence, Jira, and other sources. Ask questions via Telegram bot — get answers grounded in your organization's real data.

## Features
- **Hybrid RAG**: Dense vectors + BM25 + knowledge graph enrichment
- **Connectors**: Confluence, Jira (Notion, GitHub, Google Drive planned)
- **Smart Search**: Query expansion, date filtering, source diversity, person detection
- **Telegram Bot**: Ask questions, sync data, check status — all from Telegram
- **On-premise**: Self-hosted, your data never leaves your infrastructure
- **Multi-language**: Russian and English queries and documents

## Quick Start

### Prerequisites
- Docker and Docker Compose
- Python 3.12+
- Telegram bot token (from @BotFather)

### 1. Clone and configure
```bash
git clone <repo-url>
cd metatron-core
cp .env.example .env
# Edit .env — add your tokens and credentials
```

### 2. Start infrastructure
```bash
docker compose up -d
# Starts: Qdrant, Memgraph, PostgreSQL, Ollama
```

### 3. Install Python dependencies
```bash
pip install -e ".[dev,channels]"
```

### 4. Start Telegram bot
```bash
python -m metatron.channels.run_telegram
```

### 5. Sync data sources (in Telegram)
```
/sync confluence
/sync jira
```

Then ask any question — the bot searches your knowledge base.

### 6. Run tests
```bash
pytest tests/unit/
# Expected: 295+ tests passing
```

## Configuration
See `.env.example` for all configuration variables.

## Telegram Commands
- `/start` — Greeting and capabilities
- `/search <query>` — Explicit search
- `/sync confluence|jira` — Sync data source
- `/status` — Workspace stats
- `/clear` — Clear conversation history
- `/help` — List commands

## Architecture
See `CLAUDE.md` for detailed architecture and `docs/TODO.md` for roadmap.

## License
Apache 2.0
