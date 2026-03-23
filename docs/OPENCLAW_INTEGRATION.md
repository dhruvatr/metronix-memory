# Connecting OpenClaw to Metatron

This guide explains how to connect [OpenClaw](https://github.com/openclaw/openclaw) to Metatron so that the OpenClaw agent can search your corporate knowledge base.

Metatron exposes its knowledge base via [MCP](https://modelcontextprotocol.io/) (Model Context Protocol) at the `/mcp` endpoint. OpenClaw connects to it via [MCPorter](https://github.com/steipete/mcporter), which is bundled as a skill in OpenClaw.

## Metatron Setup

### 1. Set the MCP API Key

Add to your Metatron `.env` or environment variables:

```bash
METATRON_MCP_API_KEY=your-secure-key-here
```

Without this, the `/mcp` endpoint accepts all requests without authentication.

### 2. Ensure `/mcp` Is Accessible

Metatron serves MCP over streamable-http at `/mcp` on the same port as the API (default `8000`). Make sure this endpoint is reachable from the OpenClaw server.

**Reverse proxy:** if Metatron is behind nginx or Caddy (as in the dev environment at `ui.metatrondev.ximi.group`), you need to explicitly proxy the `/mcp` path. By default the reverse proxy may serve the SPA frontend for unknown paths and block POST requests.

**Caddy:**
```caddyfile
handle /mcp {
    reverse_proxy metatron-backend:8000
}
```

**Nginx:**
```nginx
location /mcp {
    proxy_pass http://metatron-backend:8000;
    proxy_http_version 1.1;
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

## OpenClaw Setup via MCPorter

[MCPorter](https://github.com/steipete/mcporter) is a CLI tool for calling MCP servers. It is bundled as a skill in OpenClaw and supports a daemon mode for persistent connections.

> **Note:** OpenClaw does not support `mcp.servers` as a top-level key in `openclaw.json`. Native MCP server configuration via `mcp-remote` is not available. MCPorter is the supported integration method.

### Install

MCPorter is typically installed with OpenClaw. If not available:

```bash
npm install -g mcporter
```

### Configure

Create `~/.mcporter/mcporter.json`:

```json
{
  "mcpServers": {
    "metatron": {
      "url": "https://ui.metatrondev.ximi.group/mcp",
      "headers": {
        "Authorization": "Bearer your-secure-key-here"
      }
    }
  }
}
```

Replace `ui.metatrondev.ximi.group` with your Metatron host if using a different environment.

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

The agent calls Metatron through CLI commands via the built-in `mcporter` skill. The skill prompt teaches the agent when and how to use mcporter to search the knowledge base.

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
- Verify the key in `mcporter.json` matches exactly

**421 Invalid Host header**
- Metatron's MCP SDK has DNS rebinding protection enabled by default
- Fix: deploy Metatron with the `transport_security` fix that disables DNS rebinding protection (branch `fix/mcp-api-key-auth`)
- Workaround: add `proxy_set_header Host localhost;` to your nginx/caddy config for `/mcp`

**405 Not Allowed on /mcp**
- Reverse proxy is not proxying `/mcp` to the Metatron backend — add the proxy rule (see step 2 in Metatron Setup)

**GET /mcp returns HTML instead of MCP response**
- Same issue — reverse proxy serves the SPA frontend for unknown GET paths. Add the proxy rule for `/mcp`

**mcporter connection timeout**
- Verify Metatron is running: `curl https://ui.metatrondev.ximi.group/health`
- Check firewall/reverse proxy rules
- Try `curl` from the OpenClaw server to confirm network connectivity

**mcporter: command not found**
- Run `npm install -g mcporter` on the OpenClaw server
