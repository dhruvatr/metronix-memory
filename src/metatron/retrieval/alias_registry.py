"""Auto-generated person name aliases from Jira data.

Replaces hardcoded NAME_ALIASES with a file-based registry that is
populated automatically during Jira sync. Each person seen as assignee
or reporter is registered with their display name and optional email.

Matching strategy (in priority order):
1. Custom aliases (exact match) — for nicknames like "женя" → "Evgeny …"
2. Display name parts (first/last name exact match)
3. Email prefix exact match
4. Substring match in display name (min 3 chars)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

import structlog

logger = structlog.get_logger()

_MIN_SUBSTRING_LEN = 3


class AliasRegistry:
    """Builds and maintains person name mappings from Jira data.

    File-based persistence (same pattern as SyncState). State is stored
    in ``{state_dir}/person_aliases.json``.
    """

    def __init__(self, state_dir: str = ".metatron") -> None:
        self._state_dir = state_dir
        self._registry_file = Path(state_dir) / "person_aliases.json"
        self._registry_file.parent.mkdir(parents=True, exist_ok=True)
        self._persons: dict[str, dict] = {}
        self._custom_aliases: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        """Load registry from disk."""
        if self._registry_file.exists():
            try:
                data = json.loads(self._registry_file.read_text())
                self._persons = data.get("persons", {})
                self._custom_aliases = data.get("custom_aliases", {})
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("alias_registry.load_error", error=str(e))

    def _save(self) -> None:
        """Persist registry to disk."""
        data = {
            "persons": self._persons,
            "custom_aliases": self._custom_aliases,
        }
        self._registry_file.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
        )

    def register_person(
        self,
        display_name: str,
        email: str | None = None,
    ) -> None:
        """Register a person from Jira assignee/reporter fields.

        Idempotent — skips if display_name is already known.

        Args:
            display_name: Jira displayName (e.g. "Kuzmin Konstantin").
            email: Optional email address for prefix matching.
        """
        if not display_name or not display_name.strip():
            return

        key = display_name.strip().lower()
        if key in self._persons:
            return

        parts = display_name.strip().split()
        self._persons[key] = {
            "display_name": display_name.strip(),
            "parts": [p.lower() for p in parts],
            "email_prefix": email.split("@")[0].lower() if email else None,
        }
        logger.info("alias_registry.registered", display_name=display_name.strip())
        self._save()

    def add_custom_alias(self, alias: str, display_name: str) -> None:
        """Add a manual alias mapping (e.g. "женя" -> "Evgeny Shcherbinin")."""
        self._custom_aliases[alias.lower().strip()] = display_name.strip()
        self._save()

    def resolve(self, query: str) -> List[str]:
        """Resolve a name query to possible Jira display names.

        Args:
            query: Name extracted from user message (e.g. "женя", "kuzmin").

        Returns:
            List of matching display names (may be empty).
        """
        q = query.lower().strip()
        if not q:
            return []

        # 1. Custom aliases (exact match)
        if q in self._custom_aliases:
            return [self._custom_aliases[q]]

        results: list[str] = []

        for person in self._persons.values():
            # 2. Exact match on any name part
            if q in person["parts"]:
                results.append(person["display_name"])
                continue
            # 3. Email prefix exact match
            if person.get("email_prefix") and q == person["email_prefix"]:
                results.append(person["display_name"])
                continue
            # 4. Substring match in display name (min 3 chars)
            if len(q) >= _MIN_SUBSTRING_LEN and q in person["display_name"].lower():
                results.append(person["display_name"])
                continue

        return results

    @property
    def person_count(self) -> int:
        """Number of registered persons."""
        return len(self._persons)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_registry: AliasRegistry | None = None


def get_alias_registry(state_dir: str = ".metatron") -> AliasRegistry:
    """Return the module-level AliasRegistry singleton."""
    global _registry  # noqa: PLW0603
    if _registry is None:
        _registry = AliasRegistry(state_dir=state_dir)
    return _registry


def reset_alias_registry() -> None:
    """Reset the singleton (for testing)."""
    global _registry  # noqa: PLW0603
    _registry = None
