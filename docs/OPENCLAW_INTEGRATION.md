# Connecting OpenClaw to Metatron

This guide explains how to connect [OpenClaw](https://github.com/openclaw/openclaw) to Metatron so that the OpenClaw agent can search your corporate knowledge base.

Metatron exposes its knowledge base via [MCP](https://modelcontextprotocol.io/) (Model Context Protocol) at the `/mcp` endpoint. OpenClaw connects to it using one of the methods below.

## Metatron Setup

### 1. Set the MCP API Key

Add to your Metatron `.env` or environment variables:

```bash
METATRON_MCP_API_KEY=your-secure-key-here
```

Without this, the `/mcp` endpoint accepts all requests without authentication.

### 2. Ensure `/mcp` Is Accessible

Metatron serves MCP over streamable-http at `/mcp` on the same port as the API (default `8000`). Make sure this endpoint is reachable from the OpenClaw server.

**Nginx configuration:** if Metatron is behind an nginx reverse proxy (as in the dev environment at `ui.metatrondev.ximi.group`), you need to explicitly proxy the `/mcp` path. By default nginx may serve the SPA frontend for unknown paths and block POST requests.

Add to your nginx config:

```nginx
location /mcp {
    proxy_pass http://metatron-backend:8000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

### 3. Find Your Workspace ID

MCP tools require a `workspace_id` parameter. Get yours:

```bash
curl https://ui.metatrondev.ximi.group/api/v1/workspaces
```

### 4. Verify Connectivity

```bash
curl -X POST -H "Authorization: Bearer your-secure-key-here" \
     https://ui.metatrondev.ximi.group/mcp
```

A response (even an error about missing MCP payload) confirms the endpoint is reachable and the key is valid. A `401` means the key is wrong or missing. A `405 Not Allowed` from nginx means the reverse proxy is not configured for `/mcp` (see step 2).

## Option A: mcp-remote (Recommended)

[mcp-remote](https://github.com/geelen/mcp-remote) bridges OpenClaw's stdio MCP transport to Metatron's HTTP endpoint. No additional services to run — OpenClaw manages the subprocess automatically.

### Setup

Add to `openclaw.json`:

```json
{
  "mcp": {
    "servers": {
      "metatron": {
        "command": "npx",
        "args": [
          "-y", "mcp-remote",
          "https://ui.metatrondev.ximi.group/mcp",
          "--header", "Authorization:Bearer ${METATRON_MCP_KEY}"
        ],
        "env": {
          "METATRON_MCP_KEY": "your-secure-key-here"
        }
      }
    }
  }
}
```

Replace `ui.metatrondev.ximi.group` with your Metatron host if using a different environment.

### Verify

```bash
openclaw gateway restart
openclaw mcp list
openclaw mcp show metatron
```

You should see the tools: `metatron_search`, `metatron_get`, `metatron_store`, `metatron_sync`, `metatron_status`.

### How It Works

The agent sees Metatron tools as native tools — no special prompting needed. When a user asks a question, the agent automatically decides whether to call `metatron_search` based on the tool description.

### Latency

| Scenario | Time |
|----------|------|
| First call (npx downloads package) | ~2-3 sec |
| Subsequent calls (package cached) | ~200-500ms |
| HTTP round-trip to Metatron | ~50-200ms |

## Option B: MCPorter

[MCPorter](https://github.com/steipete/mcporter) is a CLI tool for calling MCP servers. It is bundled as a skill in OpenClaw and supports a daemon mode for persistent connections.

### Install

```bash
npm install -g mcporter
```

### Configure

Create `~/.mcporter/mcporter.json`:

```json
{
  "servers": {
    "metatron": {
      "url": "https://ui.metatrondev.ximi.group/mcp",
      "headers": {
        "Authorization": "Bearer your-secure-key-here"
      }
    }
  }
}
```

### Verify

```bash
# List available tools
mcporter list metatron

# Test a search call
mcporter call metatron.metatron_search query="VPN" workspace_id="your-workspace-id"
```

### Daemon Mode (Optional)

Keep connections warm between calls:

```bash
mcporter daemon start
mcporter daemon status
```

### How It Works

Unlike mcp-remote, the agent calls Metatron through CLI commands via the built-in `mcporter` skill. The agent must be aware of mcporter — the skill prompt teaches it when and how to use it.

## Which Option to Choose

| | mcp-remote | MCPorter |
|---|---|---|
| **Setup** | Config only | Install + config |
| **Agent sees tools natively** | Yes | No (CLI via skill) |
| **Token cost per call** | ~150-250 | ~700-1400 |
| **New tools appear automatically** | Yes | No |
| **Persistent connection** | No | Yes (daemon) |
| **CLI debugging** | No | Yes |

**Start with mcp-remote** for a simpler, cheaper integration. Use MCPorter when you need persistent connections or want to debug MCP calls from the command line.

## Available Tools

| Tool | Description |
|------|-------------|
| `metatron_search` | Hybrid RAG search (vector + BM25 + knowledge graph) |
| `metatron_get` | Fetch a specific document by ID |
| `metatron_store` | Index a new document into the knowledge base |
| `metatron_sync` | Trigger a connector sync job |
| `metatron_status` | Get workspace statistics (doc count, last sync, etc.) |

## Troubleshooting

**401 Unauthorized on /mcp**
- Check that `METATRON_MCP_API_KEY` is set on the Metatron server
- Verify the key in `openclaw.json` or `mcporter.json` matches exactly

**Tools not appearing in `openclaw mcp list`**
- Run `openclaw gateway restart` after changing config
- Check OpenClaw logs for MCP connection errors

**405 Not Allowed on /mcp**
- Nginx is not proxying `/mcp` to the Metatron backend — add the `location /mcp` block to your nginx config (see step 2 in Metatron Setup)

**GET /mcp returns HTML instead of MCP response**
- Same issue — nginx serves the SPA frontend for unknown GET paths. Add the nginx proxy rule for `/mcp`

**Timeout or connection refused**
- Verify Metatron is running: `curl https://ui.metatrondev.ximi.group/health`
- Check firewall/reverse proxy rules
- Try `curl` from the OpenClaw server to confirm network connectivity

**mcporter: command not found**
- Run `npm install -g mcporter` on the OpenClaw server
