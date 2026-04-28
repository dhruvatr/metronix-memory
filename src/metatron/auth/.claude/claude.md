# Auth

## Overview
L3 — authentication and authorization. JWT token issuance/verification (HS256),
role hierarchy (viewer < editor < admin), and FastAPI dependency injection for
route protection. Supports plugin-provided auth backends (SAML, OIDC) with fallback
to built-in JWT.

## Files

### `jwt.py`
`create_token(user_id, role, workspace_ids, secret_key, expiry_hours=24) -> str`
— HS256 JWT. Payload: `sub`, `role`, `workspace_ids`, `iat`, `exp`.

`verify_token(token, secret_key) -> dict`
— Decodes and validates JWT. Raises `AuthenticationError` on `ExpiredSignatureError`
or any `InvalidTokenError`. Returns decoded payload dict.

### `rbac.py`
Role hierarchy: `_ROLE_LEVELS = {VIEWER: 0, EDITOR: 1, ADMIN: 2}`.

`check_permission(user_role, required_role) -> bool` — numeric comparison.
`require_role(user_role, required_role)` — raises `AuthenticationError` if insufficient.

### `dependencies.py`
FastAPI `Depends()` helpers for route protection.

**Auth resolution order in `get_current_user()`:**
1. Check `request.app.state.plugin_manager.get_auth_provider()`
2. If plugin provider exists → `await provider.authenticate(token)`
3. Fallback → `jwt.verify_token()` + build `User` from payload

`require_admin(user)` — wraps `get_current_user`, raises 403 if role < ADMIN.
`require_editor(user)` — wraps `get_current_user`, raises 403 if role < EDITOR.

`AuthenticationError` from core layers is converted to `HTTPException 401` here —
never leaks raw exceptions to HTTP responses.

### `user_mapping.py`
`PlatformUserMapper` — resolves channel identities (Telegram/Slack/Discord) to internal Users.
Uses `user_platform_mappings` table (migration 010).

Key methods:
- `resolve(platform, platform_user_id, display_name, auto_create) -> User | None` — looks up mapping, auto-creates User if not found
- `create_mapping(user_id, platform, platform_user_id, display_name)` — explicit mapping creation
- `list_mappings()` — list all mappings
- `get_user_mappings(user_id)` — mappings for a specific user
- `update_mapping(user_id, platform, platform_user_id, display_name)` — update existing
- `delete_mapping(user_id, platform, platform_user_id)` — remove mapping

Results cached with 30-second TTL (`_CACHE_TTL_SECONDS`).

### `user_store.py`
`UserStore` — User CRUD against PostgreSQL.
Used by `user_mapping.py` for auto-creating users.

### `api_key_store.py`
Personal API key management (`mtk_...` format) for OpenAI-compat endpoints.

## Key Patterns
- **`AuthenticationError` stays internal** — only converted to `HTTPException` at the API boundary (dependencies.py), never in jwt.py or rbac.py
- **Plugin-first auth** — `get_current_user` checks plugin provider before JWT fallback; enterprise SAML/OIDC drops in without touching core
- **Stateless JWT** — no session storage; all user context is in the token payload (`sub`, `role`, `workspace_ids`)
- **`AUTH_ENABLED=false` by default** — `OptionalAuthMiddleware` in api/ skips auth entirely unless explicitly enabled

## Dependencies
- **Depends on**: `core.exceptions` (AuthenticationError), `core.models` (User, Role), `core.config` (Settings), `storage.postgres` (PostgresStore, used by user_mapping)
- **Depended on by**: `api.middleware` (OptionalAuthMiddleware uses jwt.verify_token), `api.dependencies` (get_current_user), `api.routes.auth` (login endpoint)
