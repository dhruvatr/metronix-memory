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

echo ""; echo "TOTAL: $PASS passed, $FAIL failed"; [[ $FAIL -eq 0 ]]
