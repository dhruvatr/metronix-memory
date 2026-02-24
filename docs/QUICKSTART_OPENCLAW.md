# Connect Metatron to OpenClaw — 10-Minute Quickstart

You will:
1. Verify Metatron is running (< 2 min)
2. Get your API key (< 1 min)
3. Configure OpenClaw with Metatron (< 2 min)
4. Set environment variable (< 1 min)
5. Restart OpenClaw and verify tools (< 2 min)
6. Run your first search (< 1 min)

**Total:** ~10 minutes. Let's go.

---

## Prerequisites

- **Metatron installed and running** — If not yet installed: `curl https://app.mtrnix.com/install.sh | bash` (see [INSTALL.md](INSTALL.md) for details)
- **OpenClaw installed** — Already configured and ready to add integrations
- **Both services on same network** — Verify connectivity if on different machines
- **That's it** — No additional tools needed

---

## Step 1: Verify Metatron is Running

Run this command to check if Metatron's health endpoint is reachable:

```bash
curl http://localhost:8000/health
```

**Expected response:**
```json
{"status": "ok"}
```

**If you see a timeout or connection error:**
- Metatron is not running on localhost:8000
- Check status: `docker-compose ps` (if using Docker)
- Or check if it's running on a different host/port and adjust URLs in steps below
- See [TROUBLESHOOTING_OPENCLAW.md](TROUBLESHOOTING_OPENCLAW.md) for help

**✓ Success:** Metatron health check passed. Move to Step 2.

---

## Step 2: Get Your API Key

For local development, use the default key from the environment. Run:

```bash
cat .env 2>/dev/null | grep METATRON_SECRET_KEY || echo "Using default development key"
```

If running via Docker Compose, the key is typically generated at startup. For now, use:

```bash
export METATRON_API_KEY="${METATRON_SECRET_KEY:-dev-key-12345}"
```

(In production, retrieve from Settings → API Keys in the Metatron web UI at `http://localhost:8000`)

**✓ Success:** You have an API key. Keep it safe for Step 4.

---

## Step 3: Add Metatron to OpenClaw Configuration

Edit your OpenClaw configuration file (`~/.openclaw/config.json` or `./openclaw/config.json`):

**Find the `mcp.servers` section and add this block:**

```json
{
  "name": "metatron",
  "type": "stdio",
  "description": "Metatron knowledge management",
  "transport": {
    "type": "http",
    "url": "http://localhost:8000/mcp"
  },
  "auth": {
    "type": "bearer",
    "token_env": "METATRON_API_KEY"
  },
  "timeout_seconds": 30,
  "max_retries": 3
}
```

**For local development (stdio transport), use this instead:**

```json
{
  "name": "metatron",
  "type": "stdio",
  "command": "python",
  "args": ["-m", "metatron.mcp"],
  "env": {
    "METATRON_API_KEY": "dev-key-12345"
  }
}
```

**Save the file.**

For full configuration details, see [OPENCLAW_CONFIG.md](OPENCLAW_CONFIG.md).

**✓ Success:** Configuration added to OpenClaw.

---

## Step 4: Set Environment Variable

Make your API key available to OpenClaw:

```bash
export METATRON_API_KEY="dev-key-12345"
```

**Verify it's set:**
```bash
echo $METATRON_API_KEY
```

**Optional:** Make it permanent by adding to your shell profile:
```bash
echo 'export METATRON_API_KEY="dev-key-12345"' >> ~/.bashrc
source ~/.bashrc
```

**Windows (PowerShell):**
```powershell
$env:METATRON_API_KEY = "dev-key-12345"
```

**✓ Success:** Environment variable is set and visible.

---

## Step 5: Restart OpenClaw and Verify Tools

Close and restart your OpenClaw application (or restart the service):

```bash
# If using Docker/service:
docker-compose restart openclaw
# or
systemctl restart openclaw
```

After restart, check available tools in OpenClaw. You should see:
- `metatron_search` — Search knowledge base
- `metatron_get` — Retrieve documents
- `metatron_store` — Store information
- `metatron_status` — Check Metatron status

**Tools not appearing?**
- Verify API key is set: `echo $METATRON_API_KEY`
- Check health endpoint: `curl http://localhost:8000/health`
- See [TROUBLESHOOTING_OPENCLAW.md](TROUBLESHOOTING_OPENCLAW.md)

**✓ Success:** All Metatron tools visible in OpenClaw.

---

## Step 6: Run Your First Search

In OpenClaw, try searching your knowledge base:

```
@metatron search for: "company policy on refunds"
```

Or using the slash command:
```
/search company policy on refunds
```

**Expected response:**
- Relevant documents from your knowledge base
- Source citations (e.g., `[CONFLUENCE]`, `[JIRA]`)
- Summary with key information

**No results?**
- You may need to add data sources first: `/sync confluence`, `/sync jira`, `/sync notion`
- See [README.md](../README.md#syncing-data-sources)

**✓ Success!** You're connected and searching.

---

## What's Next?

**Add more data sources:**
- Confluence: `/sync confluence`
- Jira: `/sync jira`
- Notion: `/sync notion`
- Full details: [README.md](../README.md)

**Learn advanced search:**
- Person queries: `@metatron search for: "john's tasks"`
- Date filters: `@metatron search for: "meetings from last week"`
- See [ARCHITECTURE.md](ARCHITECTURE.md#search-pipeline)

**Explore other Metatron tools:**
- `metatron_get` — Detailed document retrieval
- `metatron_store` — Save knowledge and memories
- `metatron_status` — Check workspace health

**Detailed configuration:**
- HTTP vs stdio transport: [OPENCLAW_CONFIG.md](OPENCLAW_CONFIG.md)
- All settings and options: [ARCHITECTURE.md](ARCHITECTURE.md)

**Common issues:**
- Troubleshooting guide: [TROUBLESHOOTING_OPENCLAW.md](TROUBLESHOOTING_OPENCLAW.md)

---

**Questions?** Check [TROUBLESHOOTING_OPENCLAW.md](TROUBLESHOOTING_OPENCLAW.md) or see full docs in [ARCHITECTURE.md](ARCHITECTURE.md).

Enjoy your connected knowledge base! 🚀
