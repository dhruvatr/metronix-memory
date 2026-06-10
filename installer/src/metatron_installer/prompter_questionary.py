from __future__ import annotations

import questionary

from .wizard import Prompter


class QuestionaryPrompter(Prompter):
    def select(self, message: str, choices: list[str], default: str | None = None) -> str:
        return questionary.select(message, choices=choices, default=default).ask()

    def text(self, message: str, default: str = "") -> str:
        return questionary.text(message, default=default).ask() or default

    def password(self, message: str) -> str:
        return questionary.password(message).ask() or ""

    def confirm(self, message: str, default: bool = False) -> bool:
        return questionary.confirm(message, default=default).ask()

    def checkbox(self, message: str, choices: list[str]) -> list[str]:
        return questionary.checkbox(message, choices=choices).ask() or []
