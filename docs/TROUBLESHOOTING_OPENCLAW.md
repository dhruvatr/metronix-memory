# Troubleshooting Metatron + OpenClaw Integration

This guide helps you diagnose and fix common issues when using Metatron with OpenClaw. Start with the **Quick Diagnostic Flowchart** below, then jump to the relevant section for your issue.

---

## Quick Diagnostic Flowchart

When something isn't working, run these three checks in order:

```
1. Can I reach Metatron?
   └─ Run: curl http://localhost:8000/health
   └─ Expected: HTTP 200 response with JSON
   └─ If timeout or connection refused → See "Connection Refused / Timeout"

2. Is API key set?
   └─ Run: echo $METATRON_API_KEY
   └─ Expected: Non-empty alphanumeric string
   └─ If blank or invalid → See "Auth Failed / 401 Unauthorized"

3. Are tools visible in OpenClaw?
   └─ Check OpenClaw tools list (reload/refresh if needed)
   └─ Expected: metatron_search, metatron_get, metatron_store, metatron_status visible
   └─ If missing → See "Tools Don't Appear in OpenClaw"
```

**All three checks pass?** Then try a simple search. If search fails, see "Search Returns No Results".

---

## Issue 1: Connection Refused / Timeout

### Symptom
OpenClaw shows "timeout", "connection refused", or "failed to connect" when trying to use Metatron tools. Request hangs indefinitely or fails after 30+ seconds.

### Root Causes
- Metatron container not running
- Wrong port in configuration (default: 8000)
- Firewall blocking connection
- Network unreachable (if Metatron on different host)
- Incorrect hostname/IP in OpenClaw config

### Diagnostic Steps

**1. Check if Metatron is running:**
```bash
docker-compose ps
```
Expected output: `metatron` container shows `Up` status.

**2. Check health endpoint:**
```bash
curl http://localhost:8000/health
```
Expected: HTTP 200 with body like `{"status": "healthy", "timestamp": "2026-02-24T14:27:11Z"}`
Timeout or `Connection refused` → Metatron not running or wrong port.

**3. Check port is open:**
```bash
lsof -i :8000
```
Expected: Process `docker` or `python` listening on port 8000.
Nothing found → Service not listening, or wrong port.

**4. Check firewall (if on different host):**
```bash
ping <metatron-host>
```
Expected: Ping succeeds (host reachable).
`No route to host` → Network unreachable, check network config.

### Fixes (in order)

1. **If Metatron not running:**
   ```bash
   cd ~/.metatron && docker-compose up -d
   sleep 10  # Wait for startup
   ```
   Then retry: `curl http://localhost:8000/health`

2. **If wrong port:**
   - Check OpenClaw config file (usually `~/.openclaw/config.json`)
   - Find `metatron_url` or similar field
   - Verify it matches actual Metatron port (default `http://localhost:8000`)
   - Update if needed and restart OpenClaw

3. **If network unreachable:**
   - If Metatron on different machine, use its IP instead of `localhost`
   - Check firewall rules on Metatron host: `sudo ufw status` or `sudo iptables -L`
   - Add firewall rule if needed: `sudo ufw allow 8000/tcp`
   - Restart Metatron and retry

4. **Verify fix:**
   ```bash
   curl -v http://localhost:8000/health
   ```
   Should show HTTP 200, not timeout.

### Success Criteria
- Health check returns HTTP 200
- `curl` completes in under 2 seconds
- `docker-compose ps` shows `metatron` as `Up`

---

## Issue 2: Tools Don't Appear in OpenClaw

### Symptom
OpenClaw is connected (no timeout) but Metatron tools (`metatron_search`, `metatron_get`, etc.) don't appear in the tools list. Tools list is empty or incomplete.

### Root Causes
- Authentication failed (invalid/missing API key)
- Metatron server not responding to tool discovery requests
- OpenClaw cache not refreshed after Metatron startup
- Firewall blocking tool discovery requests
- MCP server not properly configured

### Diagnostic Steps

**1. Check API key is set:**
```bash
echo $METATRON_API_KEY
```
Expected: Non-empty string like `abc123def456...`
Blank output → API key not set.

**2. Test authentication:**
```bash
curl -H "Authorization: Bearer $METATRON_API_KEY" http://localhost:8000/health
```
Expected: HTTP 200.
HTTP 401 → Invalid API key (see Issue 3).
HTTP 403 → Permission denied.

**3. Check Metatron logs for tool discovery:**
```bash
docker-compose logs metatron | tail -50 | grep -i "tool\|discovery\|error"
```
Look for errors like "failed to load tools" or "tool discovery timeout".

**4. Force OpenClaw tool refresh:**
- Close OpenClaw app completely
- Wait 5 seconds
- Reopen OpenClaw app
- Check tools list again (should query Metatron for tools on startup)

### Fixes (in order)

1. **Set API key:**
   ```bash
   export METATRON_API_KEY="your-api-key-here"
   ```
   Get API key from Metatron setup (see QUICKSTART_OPENCLAW.md, Step 2).

2. **Verify authentication works:**
   ```bash
   curl -H "Authorization: Bearer $METATRON_API_KEY" http://localhost:8000/health
   ```
   Should return HTTP 200.

3. **Restart OpenClaw:**
   - Close app completely
   - Reopen (this triggers fresh tool discovery)
   - Wait 10 seconds for MCP connection to establish

4. **Check Metatron logs:**
   ```bash
   docker-compose logs metatron --follow
   ```
   Look for "MCP server" or "tool discovery" messages. If errors, check logs more carefully.

5. **Restart Metatron if needed:**
   ```bash
   docker-compose restart metatron
   sleep 5
   curl -H "Authorization: Bearer $METATRON_API_KEY" http://localhost:8000/health
   ```

### Success Criteria
- `curl -H "Authorization: Bearer $METATRON_API_KEY" http://localhost:8000/health` returns HTTP 200
- Tools appear in OpenClaw within 10 seconds of restart
- At least 4 tools visible: `metatron_search`, `metatron_get`, `metatron_store`, `metatron_status`

---

## Issue 3: Auth Failed / 401 Unauthorized

### Symptom
OpenClaw tries to use Metatron, gets "401 Unauthorized" error or "Authentication failed" message. Health check works, but tool use fails.

### Root Causes
- Invalid or expired API key
- Missing API key entirely
- API key format wrong (spaces, quotes, special characters)
- API key not exported as environment variable
- API key not set in OpenClaw config file
- Authorization header malformed

### Diagnostic Steps

**1. Verify API key is set:**
```bash
echo $METATRON_API_KEY
```
Expected: Non-empty string, no spaces, no quotes around it.

**2. Check API key format:**
```bash
echo $METATRON_API_KEY | wc -c
```
Expected: At least 20 characters (typical API keys 32+ chars).
Much shorter → Probably wrong key.

**3. Test key directly:**
```bash
curl -H "Authorization: Bearer $METATRON_API_KEY" http://localhost:8000/health
```
Expected: HTTP 200.
HTTP 401 → API key is invalid or revoked.

**4. Check Metatron logs for auth errors:**
```bash
docker-compose logs metatron | grep -i "auth\|unauthorized\|401" | tail -20
```

**5. Verify key is in OpenClaw config:**
```bash
# If OpenClaw uses env var, check:
echo $METATRON_API_KEY

# If OpenClaw uses config file, check:
cat ~/.openclaw/config.json | grep -i "api_key\|auth"
```

### Fixes (in order)

1. **Get the correct API key:**
   - From Metatron environment: `echo $METATRON_API_KEY`
   - Or from `.env` file: `grep METATRON_API_KEY ~/.metatron/.env`
   - Or from API (if you're admin): See OPENCLAW_CONFIG.md for API endpoint

2. **Set it correctly (no quotes or spaces):**
   ```bash
   export METATRON_API_KEY=your-actual-key-here
   # Verify with:
   echo $METATRON_API_KEY  # Should show the key, not errors
   ```

3. **Update OpenClaw configuration:**
   - If OpenClaw reads from env var: Just set `METATRON_API_KEY` as shown above
   - If OpenClaw reads from config file: Edit `~/.openclaw/config.json` and add:
     ```json
     {
       "metatron_api_key": "your-actual-key-here"
     }
     ```
   - Restart OpenClaw after config change

4. **Test the fix:**
   ```bash
   curl -H "Authorization: Bearer $METATRON_API_KEY" http://localhost:8000/health
   ```
   Should return HTTP 200, not 401.

### Success Criteria
- `curl -H "Authorization: Bearer $METATRON_API_KEY" http://localhost:8000/health` returns HTTP 200
- OpenClaw tools execute without 401 errors
- No auth-related errors in Metatron logs

---

## Issue 4: Search Returns No Results / Empty Results

### Symptom
`metatron_search` tool works (no errors) but returns empty results or "no documents found" message. Other tools work fine.

### Root Causes
- Knowledge base is empty (no documents ingested yet)
- Wrong workspace selected (if using multi-workspace)
- Search query doesn't match any documents
- Documents not yet indexed after ingestion
- Wrong search syntax or parameters

### Diagnostic Steps

**1. Check document count:**
   ```bash
   # Option A: Via OpenClaw tool
   # Run metatron_status tool in OpenClaw
   # Look for "documents: N" in result
   
   # Option B: Via API
   curl -H "Authorization: Bearer $METATRON_API_KEY" \
     http://localhost:8000/api/v1/status
   ```
   Expected: `"document_count": N` where N > 0.
   If N = 0 → No documents ingested yet.

**2. Check workspace (if applicable):**
   ```bash
   echo $METATRON_WORKSPACE
   ```
   Expected: Non-empty workspace name that matches your documents.
   Blank → Using default workspace (should be fine for single-workspace setup).

**3. Try a simple search:**
   In OpenClaw, try searching for obvious terms from your documents:
   - Names of people: "John", "Alice"
   - Project names: "ProjectX", "PROJ-123"
   - Common keywords: "meeting", "update", "bug"

   If any results appear → Index is working, try different search terms.

**4. Check Metatron logs for indexing:**
   ```bash
   docker-compose logs metatron | grep -i "index\|ingested\|chunk" | tail -20
   ```

### Fixes (in order)

1. **If knowledge base is empty:**
   ```bash
   # Ingest documents from your source (Confluence, Jira, Notion, etc.)
   # Use metatron_sync tool in OpenClaw, or:
   docker-compose exec metatron python -m metatron.agent.tools \
     sync confluence  # or jira, notion, etc.
   ```
   Wait 5-10 minutes for large datasets to be indexed.

2. **If workspace is wrong:**
   ```bash
   # List available workspaces
   curl -H "Authorization: Bearer $METATRON_API_KEY" \
     http://localhost:8000/api/v1/workspaces
   
   # Set the right workspace
   export METATRON_WORKSPACE="your-workspace-name"
   ```

3. **Try different search terms:**
   - Use simpler, more common terms
   - Try acronyms or project codes
   - Try exact names from your documents

4. **Wait for indexing (if just ingested):**
   ```bash
   # Check indexing progress
   docker-compose logs metatron | tail -50
   # Look for "Indexed N documents" or similar
   ```
   Wait for completion, then retry search.

### Success Criteria
- `metatron_status` tool shows document count > 0
- Searches for known terms return relevant results
- No errors in Metatron logs about indexing

---

## Issue 5: Slow or Timeout on Search

### Symptom
Search request is very slow (takes > 10 seconds) or times out completely. Health check is fast, but search hangs or fails.

### Root Causes
- Large dataset causing slow vector/BM25 search
- Network latency between OpenClaw and Metatron
- Database (Qdrant/Memgraph) overloaded or slow
- Timeout setting too low for large queries
- System resources exhausted (CPU, memory)

### Diagnostic Steps

**1. Measure health check speed (baseline):**
   ```bash
   time curl -H "Authorization: Bearer $METATRON_API_KEY" \
     http://localhost:8000/health
   ```
   Expected: Real < 1 second.
   If slow → Network or Metatron overloaded.

**2. Check system resource usage:**
   ```bash
   docker stats
   ```
   Expected: Metatron container CPU < 50%, Memory < 2GB.
   If high → System resource issue.

**3. Check database logs:**
   ```bash
   # Qdrant logs
   docker-compose logs qdrant | tail -20 | grep -i "error\|timeout"
   
   # Memgraph logs
   docker-compose logs memgraph | tail -20 | grep -i "error\|timeout"
   ```

**4. Check Metatron logs for slow queries:**
   ```bash
   docker-compose logs metatron | tail -50 | grep -i "slow\|timeout\|duration"
   ```

### Fixes (in order)

1. **Increase OpenClaw timeout:**
   - Edit OpenClaw config file (usually `~/.openclaw/config.json`)
   - Find `timeout` or `timeout_seconds` setting (default: 30)
   - Increase to 60-120 seconds:
     ```json
     {
       "timeout_seconds": 120
     }
     ```
   - Restart OpenClaw

2. **Check container resource limits:**
   ```bash
   # Check current docker-compose.yml
   grep -A 10 "services:" ~/.metatron/docker-compose.yml | grep -i "mem\|cpu"
   ```
   If memory limit is too low (< 2GB), increase it:
   - Edit `docker-compose.yml`
   - Add under `metatron` service: `mem_limit: 3g`
   - Run: `docker-compose up -d` (restarts with new limits)

3. **Optimize search:**
   - Use simpler, shorter queries
   - Add date filters (narrow search window)
   - Avoid wildcards at start of search terms

4. **Restart services:**
   ```bash
   docker-compose restart metatron qdrant memgraph
   sleep 10
   ```
   Then test search again.

### Success Criteria
- Search returns within 5-10 seconds
- `metatron_status` shows all services healthy
- `docker stats` shows reasonable resource usage (CPU < 50%, Mem < 2GB)

---

## Issue 6: Advanced Diagnostics

For issues not covered above, use these tools to dig deeper.

### Check Metatron Logs Directly

**View recent logs:**
```bash
docker-compose logs metatron | tail -50
```

**Follow logs in real-time (as you trigger actions in OpenClaw):**
```bash
docker-compose logs metatron --follow
```

**Search for specific errors:**
```bash
docker-compose logs metatron | grep -i "error\|exception\|failed"
```

### Verify All Services Are Healthy

```bash
docker-compose ps
```

Expected output: All containers show `Up` status, health status `healthy` (if configured).

If any service is `Exited` or `Unhealthy`:
```bash
# Check logs for that service
docker-compose logs <service-name>

# Restart it
docker-compose restart <service-name>
```

### Verify Configuration Syntax

**Check Metatron config:**
```bash
# If Metatron uses JSON config
python3 -c "import json; json.load(open(open('~/.metatron/config.json')))"
# If valid, no output. If invalid, error message shown.
```

**Check OpenClaw config:**
```bash
python3 -c "import json; json.load(open('~/.openclaw/config.json'))"
```

### Test Health Endpoint with Full Details

```bash
curl -v -H "Authorization: Bearer $METATRON_API_KEY" \
  http://localhost:8000/health
```

Output shows:
- `< HTTP/1.1 200 OK` — Status code
- `< date:` — Server response time
- Auth check result
- JSON response body

### Check OpenClaw Logs

OpenClaw logs location depends on OS:
- **macOS:** `~/Library/Logs/OpenClaw/` or check app Console
- **Linux:** `~/.openclaw/logs/` or check journalctl: `journalctl -u openclaw -n 50`
- **Windows:** `%APPDATA%\OpenClaw\logs\`

Look for:
- MCP connection attempts
- Tool discovery requests
- Auth errors
- Network timeouts

### Network Connectivity Check

If Metatron is on a different host:

```bash
# Check hostname resolves
nslookup metatron-host.com

# Check connection possible
nc -zv metatron-host.com 8000

# Ping host
ping metatron-host.com

# Check route
traceroute metatron-host.com
```

### Verify MCP Server Configuration

**Check that Metatron MCP is exposed properly:**
```bash
# Via HTTP SSE (default)
curl -H "Authorization: Bearer $METATRON_API_KEY" \
  -H "Accept: text/event-stream" \
  http://localhost:8000/mcp

# Should establish SSE connection, not error
```

---

## Still Stuck?

Follow this checklist:

1. **Re-read QUICKSTART_OPENCLAW.md** — Did you follow all setup steps?
   ```bash
   cat docs/QUICKSTART_OPENCLAW.md | head -30
   ```

2. **Verify API key one more time** (most common issue):
   ```bash
   echo "API key: $METATRON_API_KEY"
   echo "Length: $(echo -n $METATRON_API_KEY | wc -c)"
   ```
   Should show a non-empty string with 20+ characters.

3. **Confirm Metatron is actually running:**
   ```bash
   docker-compose ps
   curl http://localhost:8000/health
   ```
   Both should succeed.

4. **Check Metatron logs for actual error messages:**
   ```bash
   docker-compose logs metatron | grep -i "error" | head -20
   ```
   Read the error carefully — it usually points to the root cause.

5. **Review OPENCLAW_CONFIG.md** — Is your config correct?
   ```bash
   cat docs/OPENCLAW_CONFIG.md
   ```

6. **Try the simplest possible test:**
   ```bash
   # Test auth only
   curl -H "Authorization: Bearer $METATRON_API_KEY" \
     http://localhost:8000/health
   
   # If this works, issue is with tool use, not connection
   # If this fails, issue is with auth or connection
   ```

7. **If still failing, collect diagnostics package:**
   ```bash
   mkdir -p ~/metatron-diagnostics
   docker-compose ps > ~/metatron-diagnostics/services.txt
   docker-compose logs metatron > ~/metatron-diagnostics/metatron.log
   echo $METATRON_API_KEY | wc -c > ~/metatron-diagnostics/api-key-length.txt
   curl -v http://localhost:8000/health 2>&1 > ~/metatron-diagnostics/health-check.txt
   
   # Share ~/metatron-diagnostics/ with support (without API key content)
   ```

---

## Related Documentation

- **QUICKSTART_OPENCLAW.md** — Step-by-step setup guide
- **OPENCLAW_CONFIG.md** — Configuration reference and options
- **INSTALL.md** — Installation and prerequisites
- **ARCHITECTURE.md** — System overview and components

---

*Last updated: 2026-02-24*
*For issues not covered here, see ARCHITECTURE.md or contact support.*
