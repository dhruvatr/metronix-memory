# OpenClaw Configuration: Metatron MCP Server

Connect Metatron to OpenClaw for knowledge management capabilities using the Model Context Protocol (MCP).

## Overview

This guide walks you through configuring Metatron as an MCP server for use with OpenClaw. Metatron provides a rich knowledge base interface with searching, retrieval, and storage capabilities.

**Setup time:** ~5 minutes  
**Prerequisite:** Metatron installed and running (see [INSTALL.md](INSTALL.md))  
**Two transport options:** HTTP (production-recommended) or stdio (development)

## Prerequisites

Before configuring OpenClaw, ensure:

1. **Metatron is running**
   - Via installer: `~/.metatron/metatron-app`
   - Via Docker Compose: `docker-compose up -d`
   - Verify health: `curl http://localhost:8000/health`

2. **You have an API key**
   - Generated automatically on first Metatron startup
   - Located in workspace settings (API Keys section)
   - If not found, see [GETTING_STARTED.md](GETTING_STARTED.md#getting-your-api-key)

3. **Network accessibility**
   - If using HTTP transport: Metatron API must be reachable from your OpenClaw machine
   - Default: `http://localhost:8000` (local same-machine)
   - Remote: `http://metatron-server.example.com:8000` (adjust host/port as needed)

4. **OpenClaw version compatibility**
   - MCP support: OpenClaw 2.0+
   - Verify your version in OpenClaw settings or `openclaw --version`

## HTTP Transport (Recommended for Production)

Use HTTP when:
- Metatron runs on a separate server
- You need production-grade reliability
- OpenClaw and Metatron are on different machines

### Configuration Format

See `docs/config.example.json` for the complete HTTP example with all fields explained. Here's a quick overview:

**Key fields to customize:**

| Field | Example | Notes |
|-------|---------|-------|
| `name` | `"metatron"` | Server name in OpenClaw |
| `type` | `"stdio"` | Server type (OpenClaw format) |
| `transport.type` | `"http"` | Use HTTP transport |
| `transport.url` | `http://localhost:8000/mcp` | Where Metatron is running |
| `auth.type` | `"bearer"` | Authentication type |
| `auth.token_env` | `METATRON_API_KEY` | Environment variable with your API key |
| `timeout_seconds` | `30` | How long to wait for responses |
| `max_retries` | `3` | Retry on transient errors |

### Setup Steps

1. **Get your Metatron API key**
   - Log into Metatron at `http://localhost:8000` (or your server URL)
   - Navigate to Settings → API Keys
   - Copy the active API key

2. **Set the API key environment variable**
   ```bash
   export METATRON_API_KEY="your-api-key-here"
   ```

3. **Configure OpenClaw**
   - Copy the HTTP example from `docs/config.example.json`
   - Paste into OpenClaw's `mcp.servers[]` configuration
   - Update `transport.url` to your Metatron server (e.g., `http://metatron-server:8000/mcp`)
   - Verify the environment variable is set

4. **Test the connection**
   - Restart OpenClaw: `openclaw restart` (or equivalent for your setup)
   - Check OpenClaw logs for "metatron" server status: `openclaw logs | grep metatron`
   - Run `/mcp tools metatron` to list available tools

### Firewall & Network Notes

- **Local development:** HTTP localhost works automatically
- **Remote server:** 
  - Ensure firewall allows port 8000 (or your custom port)
  - Use HTTPS in production: `https://metatron-server.com:8000`
  - Generate SSL certificate (see [ARCHITECTURE.md](ARCHITECTURE.md#tls-setup))

## Stdio Transport (Development & Local)

Use stdio when:
- OpenClaw and Metatron run on the same machine
- You're developing locally
- You want minimal network overhead

### Configuration Format

See `docs/config.example.json` for the stdio example. Quick overview:

**Key fields:**

| Field | Example | Notes |
|-------|---------|-------|
| `name` | `"metatron"` | Server name in OpenClaw |
| `type` | `"stdio"` | Server type |
| `transport.type` | `"stdio"` | Use stdio transport |
| `transport.command` | `"python"` | Command to run Metatron |
| `transport.args` | `["-m", "metatron.mcp"]` | Arguments to the command |
| `env.METATRON_API_KEY` | `"your-key"` | API key for authentication |

### Setup Steps

1. **Verify Python 3.12+ is installed**
   ```bash
   python3 --version  # Should be 3.12 or higher
   ```

2. **Get your Metatron API key** (same as HTTP above)
   - Log into Metatron
   - Settings → API Keys
   - Copy the active key

3. **Copy the stdio configuration example**
   - From `docs/config.example.json`
   - Paste into OpenClaw's `mcp.servers[]`
   - Update `env.METATRON_API_KEY` with your actual key

4. **Test the connection**
   - Restart OpenClaw
   - Check logs: `openclaw logs | grep -i stdio`
   - Run `/mcp tools metatron` to list available tools

### Limitations

- **Single process:** Only one OpenClaw instance can use stdio transport at a time
- **Startup time:** ~2 seconds overhead per request (Python startup + initialization)
- **Not suitable for:** Multiple concurrent requests, production servers

## API Key & Authentication

### Getting Your API Key

**Method 1: From Metatron Web UI** (simplest)
1. Open `http://localhost:8000` (or your server URL)
2. Log in with your workspace credentials
3. Go to Settings → API Keys
4. Click "Generate New" or copy existing active key
5. Copy to clipboard

**Method 2: From CLI**
```bash
# Requires Metatron CLI installed
metatron api-key get --workspace default
```

**Method 3: Check configuration file**
```bash
# If using installer
cat ~/.metatron/config.json | jq '.api_key'
```

### API Key Format

Metatron uses **Bearer tokens** for authentication:
```
Authorization: Bearer YOUR_API_KEY_HERE
```

The token is a 32+ character alphanumeric string. Example format:
```
mtk_prod_abc123def456ghi789jkl012mno345
```

### Storage: Environment Variable (Recommended)

Use environment variables for security — never embed secrets in config files:

```bash
# Set temporarily (current shell session)
export METATRON_API_KEY="mtk_prod_abc123..."

# Set permanently (add to ~/.bashrc, ~/.zshrc, or .env)
echo 'export METATRON_API_KEY="mtk_prod_abc123..."' >> ~/.bashrc
source ~/.bashrc
```

Then reference in config:
```json
"auth": {
  "type": "bearer",
  "token_env": "METATRON_API_KEY"
}
```

### Rotating Your API Key

If you suspect your key is compromised:

1. Log into Metatron Web UI
2. Settings → API Keys
3. Click "Revoke" on the old key
4. Generate a new key
5. Update your environment variable: `export METATRON_API_KEY="new-key"`
6. Restart OpenClaw and Metatron: `docker-compose restart metatron` or `openclaw restart`

### Testing Authentication

Verify your API key works:

```bash
# Test with curl
curl -H "Authorization: Bearer $METATRON_API_KEY" \
  http://localhost:8000/health

# Expected response
# {"status":"ok","timestamp":"2026-02-24T10:00:00Z"}
```

If you get `{"status":"unauthorized"}`, check:
- API key is correct (no extra spaces or characters)
- API key hasn't been revoked
- Bearer prefix is present in the request header

## Troubleshooting Quick Reference

### "Tools don't appear in OpenClaw"

**What to check:**
1. Verify Metatron is running: `curl http://localhost:8000/health`
2. Verify API key is correct and not revoked
3. Check OpenClaw server logs: `openclaw logs | grep -i metatron`
4. Run `/mcp tools metatron` in OpenClaw to manually list tools

**Fix:**
- Restart OpenClaw: `openclaw restart`
- Verify environment variable: `echo $METATRON_API_KEY` (should not be empty)
- Check API key in Metatron Web UI hasn't expired

### "Connection timeout"

**What to check:**
1. Is Metatron running? `curl http://localhost:8000/health`
2. Is the host/port correct? (localhost vs your server address)
3. Is the port accessible? `netstat -tlnp | grep 8000` (on Metatron machine)
4. Is firewall blocking? Try: `telnet localhost 8000`

**Fix:**
- Start Metatron: `docker-compose up -d` or `~/.metatron/metatron-app`
- Verify correct host/port in config: should match `METATRON_HOST:METATRON_PORT`
- Allow firewall port: `sudo ufw allow 8000` (on Ubuntu/Debian)
- Check OpenClaw logs for detailed error

### "Authentication failed / 401 error"

**What to check:**
1. API key format: starts with `mtk_`?
2. Environment variable is set: `echo $METATRON_API_KEY`
3. No extra spaces around key
4. Key hasn't been revoked in Metatron Web UI

**Fix:**
- Get a fresh API key from Metatron Settings → API Keys
- Verify new key with curl: `curl -H "Authorization: Bearer <key>" http://localhost:8000/health`
- Update environment variable and restart OpenClaw

### "Config parsing error"

**What to check:**
1. Is the JSON valid? Use [jsonlint.com](https://jsonlint.com) to validate
2. Are all required fields present? See `docs/config.example.json`
3. No trailing commas in JSON arrays/objects?

**Fix:**
- Copy the example from `docs/config.example.json` again
- Validate JSON syntax before saving
- Check for common mistakes: missing quotes, trailing commas

## Next Steps

1. **Choose your transport:** HTTP (production) or stdio (local development)
2. **Copy the example:** From `docs/config.example.json`
3. **Customize 3-4 fields:** API key, host (if not localhost), port (if not 8000)
4. **Test connection:** `/mcp tools metatron` in OpenClaw
5. **Read CONNECTORS.md:** Learn about available tools and data sync

## Related Documentation

- [INSTALL.md](INSTALL.md) — How to install and run Metatron
- [ARCHITECTURE.md](ARCHITECTURE.md#mcp-server-architecture) — How MCP server works internally
- [CONNECTORS.md](CONNECTORS.md#mcp-server) — MCP tools and data connectors
- [GETTING_STARTED.md](GETTING_STARTED.md) — First steps after installation
- Full troubleshooting: See `docs/TROUBLESHOOTING.md` (next plan)

---

**Questions?** Check the [Issue Tracker](https://github.com/openclaw/metatron/issues) or open a discussion.
