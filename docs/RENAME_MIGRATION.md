# Metronix Memory Internal Rename Migration

This document defines how to migrate the internal `metatron` compatibility surface to `metronix-memory` branding without breaking every import, environment variable, CLI command, and MCP integration in one dramatic afternoon.

## Goal

Move the codebase from legacy internal naming to the new product naming:

- product: `Metronix Memory`
- current repo path: `metatroncore`
- target repo name: `metronix-memory`
- companion UI repo: `metronix-console`

## Non-Goal

This is not a one-commit search-and-replace.

The current `metatron` name exists in:
- Python package paths
- import statements across `src/` and `tests/`
- CLI entry points
- environment variable names
- MCP tool identifiers
- config examples
- persisted workspace/config state paths

If we change all of those at once, we break:
- editable installs
- downstream scripts
- OpenClaw integrations
- existing environments and `.env` files
- tests

## Current Compatibility Surface

### Python package and imports

- package root: `src/metatron`
- imports across app and tests: `from metatron...`
- wheel target in `pyproject.toml`: `packages = ["src/metatron"]`

### CLI commands

- existing commands: `metatron`, `metatron-api`
- new aliases already added: `metronix-memory`, `metronix-memory-api`

### Environment variables

The config layer currently depends on `METATRON_*` names, including:

- `METATRON_ENV`
- `METATRON_HOST`
- `METATRON_PORT`
- `METATRON_LOG_LEVEL`
- `METATRON_SECRET_KEY`

Plus related compatibility names used in docs and tests:

- `METATRON_API_KEY`
- `METATRON_WORKSPACE`

### MCP / OpenClaw integration surface

The current OpenClaw and MCP compatibility layer still uses:

- `python -m metatron.app`
- `python -m metatron...`
- `metatron_search`
- `metatron_get`
- `metatron_store`
- `metatron_status`
- `metatron_sync`

These identifiers are part of the integration contract and should not be broken casually.

## Recommended Migration Strategy

### Phase A: Public Branding Layer

Status: mostly done.

What belongs here:
- README naming
- package display name
- contributor docs
- architecture and product docs
- “Metronix Memory” as the public product name

What must stay compatible:
- module imports
- env vars
- MCP tool IDs
- service commands

### Phase B: Dual-Stack Compatibility Layer

Add new internal names while keeping legacy names working.

Required work:

1. Package alias strategy
   - keep `src/metatron` as canonical temporarily
   - add a new importable wrapper package such as `src/metronix_memory`
   - re-export public entry points from the wrapper package

2. CLI compatibility
   - keep `metatron` and `metatron-api`
   - add `metronix-memory` and `metronix-memory-api`
   - document that the old commands are deprecated but supported

3. Environment variable dual-read
   - add support for `METRONIX_*` variables
   - continue reading `METATRON_*`
   - define precedence explicitly
   - emit deprecation warnings for legacy names in development logs

4. Config and state paths
   - support both legacy and new state directories if needed
   - examples:
     - legacy: `.metatron`, `~/.metatron`
     - target: `.metronix`, `~/.metronix`

5. MCP naming policy
   - decide whether MCP tool IDs stay `metatron_*` long-term
   - if changing them, ship aliases before removing old names

### Phase C: Internal Source Migration

Once compatibility exists, migrate the source tree deliberately.

Required work:

1. Add `src/metronix_memory`
2. Move or mirror modules from `src/metatron`
3. Update imports incrementally
4. Keep tests green after each slice
5. Maintain legacy shim imports during the transition

Suggested slices:
- `core`
- `api`
- `auth`
- `llm`
- `ingestion`
- `retrieval`
- `connectors`
- `agent`
- `workspaces`

### Phase D: Deprecation and Removal

Only after at least one compatibility window:

- remove legacy CLI names
- remove legacy env var names
- remove legacy package imports
- remove legacy MCP aliases if intentionally changed

## Concrete Execution Plan

### Step 1: Add package alias scaffolding

- create `src/metronix_memory/__init__.py`
- expose compatibility imports from `metatron`
- verify `python -c "import metronix_memory"` works

### Step 2: Add dual environment variable support

Update `src/metatron/core/config.py` so each renamed setting can read:

- preferred: `METRONIX_*`
- fallback: `METATRON_*`

Document precedence:
- if both are set, prefer `METRONIX_*`

### Step 3: Add state/config directory compatibility

Audit references to:

- `.metatron`
- `~/.metatron`

Introduce helpers that search in order:

1. new `metronix` path
2. legacy `metatron` path

### Step 4: Decide MCP contract policy

Recommended default:

- keep `metatron_*` MCP tool IDs for now
- update descriptions to say “Metronix Memory”
- add `metronix_*` aliases only if there is a clear downstream need

Reason:
- tool IDs are integration contracts, not just labels

### Step 5: Add test coverage for compatibility

Add explicit tests for:

- legacy env vars still load
- new env vars override legacy env vars
- both CLI names resolve
- both package import paths work once aliasing is added

## Risks

### High risk

- renaming `src/metatron` directly without aliasing
- changing `METATRON_*` vars without dual-read
- renaming MCP tools without alias support

### Medium risk

- changing config/state directory names without migration logic
- changing example commands before code supports them

### Low risk

- public docs and branding changes
- adding new CLI aliases
- adding package metadata and new product labels

## Recommendation

Do **not** rename `src/metatron` directly yet.

The next implementation step should be:

1. add a `metronix_memory` package alias
2. add dual-read support for `METRONIX_*` env vars
3. add tests for both old and new naming paths

That gives us a controlled bridge instead of a ceremonial outage.
