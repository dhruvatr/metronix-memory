#!/usr/bin/env bash
# Tests for the OpenClaw wiring in install.sh. Sandboxed; no real ~/.openclaw.
# The CLI-edit path uses a fake `openclaw` stub on PATH — no real OpenClaw needed.
# Run: bash tests/installer/test_wire_openclaw.sh
set -u
INSTALL="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/install.sh"
REPO="$(dirname "$INSTALL")"
PASS=0; FAIL=0
chk() { if [[ "$2" == "$3" ]]; then echo "  PASS: $1"; PASS=$((PASS+1)); else echo "  FAIL: $1 (got [$2] want [$3])"; FAIL=$((FAIL+1)); fi; }

echo "Task3: flag parses into global, usage lists it"
out="$(bash -c "source '$INSTALL'; parse_args --wire-openclaw --agent-id abc123; echo \"\$WIRE_OPENCLAW|\$AGENT_ID\"")"
chk "flag parsed" "$out" "true|abc123"
chk "usage lists --wire-openclaw" "$(bash -c "source '$INSTALL'; usage" | grep -c -- '--wire-openclaw')" "1"
chk "WIRE_OPENCLAW defaults false" "$(bash -c "source '$INSTALL'; echo \$WIRE_OPENCLAW")" "false"

echo "Task4: detection helpers"
hd="$(mktemp -d)"
chk "openclaw_found: neither binary nor dir -> false" "$(HOME="$hd" PATH="/usr/bin:/bin" bash -c "source '$INSTALL'; openclaw_found && echo yes || echo no")" "no"
mkdir -p "$hd/.openclaw"
chk "openclaw_found: dir only -> true" "$(HOME="$hd" bash -c "source '$INSTALL'; openclaw_found && echo yes || echo no")" "yes"
chk "openclaw_cli_available: dir only, no binary -> false" "$(HOME="$hd" PATH="/usr/bin:/bin" bash -c "source '$INSTALL'; openclaw_cli_available && echo yes || echo no")" "no"
stub="$(mktemp -d)"; printf '#!/usr/bin/env bash\nexit 0\n' > "$stub/openclaw"; chmod +x "$stub/openclaw"
chk "openclaw_cli_available: binary on PATH -> true" "$(HOME="$hd" PATH="$stub:$PATH" bash -c "source '$INSTALL'; openclaw_cli_available && echo yes || echo no")" "yes"

echo "Task4b: json_escape / openclaw_mcp_json"
chk "json_escape: plain string unchanged" "$(bash -c "source '$INSTALL'; json_escape 'plain'")" "plain"
chk "json_escape: escapes quote and backslash" "$(bash -c "source '$INSTALL'; json_escape 'a\"b\\c'")" 'a\"b\\c'
payload="$(bash -c "source '$INSTALL'; H_URL=http://h:8000/mcp; H_KEY=KEY123; H_AGENT=AID9; openclaw_mcp_json")"
chk "payload has url" "$(printf '%s' "$payload" | grep -c 'http://h:8000/mcp')" "1"
chk "payload has bearer key" "$(printf '%s' "$payload" | grep -c 'Bearer KEY123')" "1"
chk "payload has agent header" "$(printf '%s' "$payload" | grep -c 'X-Agent-Id":"AID9')" "1"
chk "payload has streamable-http transport" "$(printf '%s' "$payload" | grep -c 'streamable-http')" "1"
chk "payload is one line" "$(printf '%s' "$payload" | wc -l | tr -d ' ')" "0"

echo ""; echo "TOTAL: $PASS passed, $FAIL failed"; [[ $FAIL -eq 0 ]]
