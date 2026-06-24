# Connecting an Agent

Metronix exposes an MCP server at `/mcp`. Connecting an agent does two things: it registers
Metronix as an MCP server in the agent's runtime (giving it Metronix's knowledge search and
memory tools), and it tells the agent to use Metronix as its durable-memory store.

There are two ways to do this:

- **[Prompt-based setup](#prompt-based-setup)** — paste a few prompts into the agent and let
  it configure itself. Fastest path; recommended for most users.
- **[Manual setup](#manual-setup)** — wire the MCP connection and memory policy by hand, with
  no LLM involved. Use this when you want a deterministic, reviewable procedure or your
  runtime is not agent-driven.

Both paths produce the same result. Do this **after** the backend is running and
`METRONIX_MCP_API_KEY` is set in `.env` (see [`install.md`](install.md)).

## What you need

Either path uses the same four values. Give them to the agent, or have them ready before you
edit config by hand.

| Value | Example | Where to get it |
|---|---|---|
| `METRONIX_URL` | `http://localhost:8001/mcp` | Your MCP endpoint. |
| `METRONIX_MCP_API_KEY` | token from `.env` | `METRONIX_MCP_API_KEY` in the server `.env`. Sent as `Authorization: Bearer ...`; `/mcp` returns 401 without it. |
| `AGENT_UUID` | `my-agent-001` | Any stable, unique id you choose, or the `id` returned by `POST /api/v1/agents`. |
| `DEFAULT_WORKSPACE_ID` | `MTRNIX` | The Workspaces UI, or `GET /api/v1/workspaces`. Defaults to `MTRNIX`. |

> **Restart matters.** Most runtimes load MCP servers only at startup. After you register
> the MCP server (either path), restart the agent runtime so the `metronix_*` tools become
> available before you configure the memory policy.

## Runtime-specific guides

Both setup paths register an MCP server, but **where** that configuration lives differs per
runtime (config file location and format). If you use one of these runtimes, its guide gives
the concrete paths — use it alongside whichever path you choose below:

- **Hermes** — [`docs/integrations/hermes.md`](docs/integrations/hermes.md)
- **Cursor** — [`docs/integrations/cursor.md`](docs/integrations/cursor.md)
- **Claude Desktop** — [`docs/integrations/claude-desktop.md`](docs/integrations/claude-desktop.md)
- **LibreChat** — [`docs/integrations/librechat.md`](docs/integrations/librechat.md)
- **OpenClaw** — [`docs/integrations/openclaw.md`](docs/integrations/openclaw.md)
- **Open WebUI** — [`docs/integrations/openwebui.md`](docs/integrations/openwebui.md)

For any other MCP client, the connection details below are runtime-neutral.

---

## Prompt-based setup

Setup is **three prompts** you paste into your agent, in order. The full text of each prompt
lives on a dedicated page: **[`prompts.md`](prompts.md)**.

1. **Prompt 1 — Install Metronix as an MCP server.** Registers Metronix and exposes its
   knowledge search (RAG) and memory tools. Memory use is optional at this stage. **Restart
   the runtime afterward.**
2. **Prompt 2 — Make Metronix the primary and only memory store.** Flips durable memory from
   optional to mandatory.
3. **Prompt 3 — Migrate existing memory.** Run only if the agent already holds durable
   memory.

Run Prompt 1 in the first session, restart, then run Prompts 2 and 3 in the next session.
See [`prompts.md`](prompts.md) for the prompts, parameters, and exact ordering. For where the
MCP server config lives in your client, see [Runtime-specific guides](#runtime-specific-guides).

---

## Manual setup

This is the deterministic, no-LLM equivalent of the three prompts. It has three stages:
register the MCP server, set the memory policy, and (optionally) migrate existing memory.

### Stage 1 — Register the MCP server

Add Metronix as an MCP server in your runtime's configuration file. Every runtime needs the
same connection details:

- **URL:** `{{METRONIX_URL}}` (e.g. `http://localhost:8001/mcp`)
- **Header:** `Authorization: Bearer {{METRONIX_MCP_API_KEY}}` — required; `/mcp` returns
  401 without it.
- **Header:** `X-Agent-Id: {{AGENT_UUID}}` — required for agent-scoped memory and
  observability. Use the same `AGENT_UUID` in memory tool arguments.
- **Timeout:** 180 seconds. **Connect timeout:** 60 seconds.

Most MCP clients use an `mcpServers` JSON block. The Metronix entry looks like this — adapt
the key names to your client if it differs:

```json
{
  "mcpServers": {
    "metronix": {
      "url": "http://localhost:8001/mcp",
      "headers": {
        "Authorization": "Bearer <METRONIX_MCP_API_KEY>",
        "X-Agent-Id": "<AGENT_UUID>"
      }
    }
  }
}
```

Hermes uses YAML (`mcp_servers.metronix`) with the same `url` / `headers` fields — see its
guide below.

#### Where the files live

The config file and the always-on instruction file (used in [Stage 2](#stage-2--set-the-memory-policy))
differ per runtime. Common default locations — confirm exact, version-specific paths in the
[runtime-specific guides](#runtime-specific-guides):

| Runtime | MCP server config file | Always-on / persona file (Stage 2) |
|---|---|---|
| **Cursor** | `~/.cursor/mcp.json` (global) or `<project>/.cursor/mcp.json` | `<project>/.cursor/rules/*.mdc` |
| **Claude Desktop** | macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`; Windows: `%APPDATA%\Claude\claude_desktop_config.json` | No per-turn system file — use your own long-lived instruction store |
| **Hermes** | `~/.hermes/config.yaml` (YAML) | `~/.hermes/SOUL.md` (or `/root/.hermes/SOUL.md` when running as root) |
| **LibreChat** | `librechat.yaml` (`mcpServers:`) | Agent / custom instructions |
| **OpenClaw** | see [`docs/integrations/openclaw.md`](docs/integrations/openclaw.md) | see its guide |
| **Open WebUI** | Connects to Metronix as an OpenAI-compatible backend, not an MCP client — see [`docs/integrations/openwebui.md`](docs/integrations/openwebui.md) | n/a |

**Restart the agent runtime** so the `metronix_*` tools load.

### Stage 2 — Set the memory policy

Most runtimes load a persona / system / always-on instruction file at the start of every
turn — the file listed in the right-hand column of the [Stage 1 table](#where-the-files-live)
for your runtime. Add the following block to that file by hand — append it without
overwriting existing content, and edit the live file the runtime actually loads, not a
backup. This is what tells the agent which `workspace_id` / `agent_id` to use and that
Metronix is its durable-memory store:

```text
--- metronix-config ---
Durable memory lives in Metronix MCP. ALWAYS use the metronix_memory_* tools,
with workspace_id="{{DEFAULT_WORKSPACE_ID}}" and agent_id="{{AGENT_UUID}}".
kind: fact (default) | preference (auto-injected) | pinned (must-not-vanish).
Do NOT use local/built-in memory for durable knowledge and do NOT silently
fall back to it. If Metronix is unreachable, say so instead of storing
durable knowledge locally.
--- end metronix-config ---
```

> To roll this out in two stages (optional first, then mandatory) as the prompts do, start
> with wording that says memory use is *optional*, then replace the block body with the
> mandatory rule above once you've confirmed the tools work.

Verify the connection and policy.
You can do this in two ways:

**Option A — through your MCP client** (invoke the tools from the client's tool interface, or
ask the connected agent to run them):

- `metronix_status(workspace_id="{{DEFAULT_WORKSPACE_ID}}")` — knowledge-base connectivity.
- `metronix_memory_list(workspace_id="{{DEFAULT_WORKSPACE_ID}}", agent_id="{{AGENT_UUID}}", limit=5)` — memory channel reachable.

**Option B — over REST with `curl`** (uses a REST API token — see the token note in
[Stage 3, Option B](#stage-3--migrate-existing-memory-optional)):

```bash
# Connectivity
curl http://localhost:8001/health

# Memory channel
curl "http://localhost:8001/api/v1/memory/records?workspace_id={{DEFAULT_WORKSPACE_ID}}&agent_id={{AGENT_UUID}}&limit=5" \
  -H "Authorization: Bearer $TOKEN"
```

Confirm the rule is saved and any pre-existing instructions in the file are intact.

### Stage 3 — Migrate existing memory (optional)

Only if the agent already holds durable knowledge elsewhere. Store each durable item — facts,
preferences, pinned instructions — in Metronix. There are two ways to run the calls:

**Option A — through your MCP client** (reuses the Stage 1 connection). Once the `metronix_*`
tools are loaded, invoke the memory tools from your client's tool interface, or instruct the
connected agent to call them. The tool call takes these arguments:

```text
metronix_memory_store(
  workspace_id="{{DEFAULT_WORKSPACE_ID}}",
  agent_id="{{AGENT_UUID}}",
  content=<self-contained text>,
  scope="per_agent",
  source_type="conversation",
  kind=<fact|preference|pinned>,
  importance_score=0.7
)
```

Use `metronix_memory_batch_store` for more than five items. Full tool reference:
[`docs/MCP_API.md`](docs/MCP_API.md).

**Option B — over REST with `curl`** (no MCP client needed; fully deterministic). Post each
record to the memory API. This path uses a REST API token (JWT) — **distinct from the MCP API
key**.

First get a token. If `METRONIX_AUTH_ENABLED=false` (the development default), auth is off and
you can skip this — omit the `Authorization` header. Otherwise, log in to obtain a JWT (or use
a personal API key `mtk_...`); see [Authentication in `docs/API.md`](docs/API.md#authentication):

```bash
TOKEN=$(curl -s -X POST "http://localhost:8001/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com","password":"your-password"}' | jq -r .token)
```

Then post each record:

```bash
curl -X POST "http://localhost:8001/api/v1/memory/records?workspace_id={{DEFAULT_WORKSPACE_ID}}" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "content": "<self-contained text>",
    "agent_id": "{{AGENT_UUID}}",
    "scope": "PER_AGENT",
    "kind": "fact",
    "importance_score": 0.7
  }'
```

Either way, always scope to both `workspace_id` and `agent_id`, and don't store duplicates.
For the memory model and access paths, see [`docs/guides/memory.md`](docs/guides/memory.md).

After migrating, retire the originals you own exclusively (clear them so there is one source
of truth), but leave shared or external stores intact. Verify that nothing was left behind —
with `metronix_memory_list(...)` (Option A) or `GET /api/v1/memory/records` (Option B).

## Memory kinds

Metronix classifies durable memory by `kind`:

- `fact` (default) — durable factual statements.
- `preference` — stable user or team preferences; auto-injected into context.
- `pinned` — explicit must-remember instructions.

See [`docs/guides/memory.md`](docs/guides/memory.md) for the full memory model, freshness
lifecycle, and access paths.
