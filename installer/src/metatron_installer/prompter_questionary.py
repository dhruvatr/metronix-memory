from __future__ import annotations

import questionary

from .wizard import Prompter


class QuestionaryPrompter(Prompter):
    def select(self, message, choices, default=None):
        return questionary.select(message, choices=choices, default=default).ask()

    def text(self, message, default=""):
        return questionary.text(message, default=default).ask() or default

    def password(self, message):
        return questionary.password(message).ask() or ""

    def confirm(self, message, default=False):
        return questionary.confirm(message, default=default).ask()

    def checkbox(self, message, choices):
        return questionary.checkbox(message, choices=choices).ask() or []
