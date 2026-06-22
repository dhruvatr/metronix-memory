# Hermes Integration

Hermes can connect to Metatron through MCP.

Example server configuration:

```yaml
mcp_servers:
  metatron:
    url: http://localhost:8001/mcp
    headers:
      Authorization: "Bearer <METATRON_MCP_API_KEY>"
      X-Agent-Id: "<AGENT_UUID>"
    timeout: 180
    connect_timeout: 60
```

Restart Hermes after changing MCP configuration. Then verify:

```text
metatron_status(workspace_id="MTRNIX")
metatron_memory_list(workspace_id="MTRNIX", agent_id="<AGENT_UUID>", limit=5)
```

For prompt-driven setup, paste the prompt from `../../connecting_to_agent.md`.
