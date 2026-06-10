from __future__ import annotations

from typing import Protocol

from .config import InstallerConfig, LlmProvider, Mode, Profile, defaults_for
from .profiles import OPTIONAL_PROFILES, validate_profile_llm

_PROVIDERS_NEEDING_KEY = {LlmProvider.DEEPSEEK, LlmProvider.OPENROUTER, LlmProvider.CUSTOM}
_KEY_PROMPT = {
    LlmProvider.DEEPSEEK: "DeepSeek API key",
    LlmProvider.OPENROUTER: "OpenRouter API key",
    LlmProvider.CUSTOM: "Custom LLM API key",
}


class Prompter(Protocol):
    def select(self, message: str, choices: list[str], default: str | None = None) -> str: ...
    def text(self, message: str, default: str = "") -> str: ...
    def password(self, message: str) -> str: ...
    def confirm(self, message: str, default: bool = False) -> bool: ...
    def checkbox(self, message: str, choices: list[str]) -> list[str]: ...


def run_wizard(prompter: Prompter) -> InstallerConfig:
    mode = Mode(prompter.select("Deployment mode", [m.value for m in Mode]))
    provider = LlmProvider(prompter.select("LLM provider", [p.value for p in LlmProvider]))

    cfg = defaults_for(mode, Profile.MINIMAL)
    cfg.llm_provider = provider
    if provider in _PROVIDERS_NEEDING_KEY:
        cfg.llm_api_key = prompter.password(_KEY_PROMPT[provider])

    profile = Profile(prompter.select("Deployment profile", [p.value for p in Profile]))
    cfg.profile = profile
    if profile is Profile.CUSTOM:
        cfg.enabled_profiles = prompter.checkbox(
            "Select optional services", list(OPTIONAL_PROFILES)
        )

    # minimal + self-hosted ollama needs an external host.
    if provider is LlmProvider.OLLAMA and profile is Profile.MINIMAL:
        cfg.ollama_host = prompter.text("External Ollama host (http://host:11434)")
    validate_profile_llm(cfg.profile, cfg.llm_provider, cfg.ollama_host)

    if prompter.confirm("Configure optional integrations?", default=False):
        cfg.openai_compat_key = prompter.password("OpenAI-compat API key (blank to skip)")
        cfg.mcp_api_key = prompter.password("MCP API key (blank to skip)")
        cfg.telegram_bot_token = prompter.password("Telegram bot token (blank to skip)")

    return cfg
