from __future__ import annotations

import argparse
from pathlib import Path

from . import __version__, ui
from .answers import load_answers_yaml
from .config import InstallerConfig, Mode, Profile, defaults_for
from .docker import CommandResult, DockerShell
from .envfile import atomic_write
from .runner import launch_stack, render_artifacts


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="metatron-installer")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--config", help="Path to a non-interactive answers YAML")
    p.add_argument("--non-interactive", action="store_true")
    p.add_argument("--dry-run", action="store_true", help="Render artifacts, do not launch Docker")
    return p


def _resolve_config(args: argparse.Namespace) -> InstallerConfig:
    if args.config:
        return load_answers_yaml(args.config)
    if args.non_interactive:
        # No config file but non-interactive: use safe server/minimal defaults.
        return defaults_for(Mode.SERVER, Profile.MINIMAL)
    from .prompter_questionary import QuestionaryPrompter  # Task 12 provides this
    from .wizard import run_wizard
    return run_wizard(QuestionaryPrompter())


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[3]
    template_path = repo_root / ".env.example"
    template = template_path.read_text() if template_path.exists() else ""

    cfg = _resolve_config(args)
    env_text, compose_profiles = render_artifacts(cfg, template)

    if args.dry_run:
        ui.info(f"COMPOSE_PROFILES={compose_profiles!r}")
        ui.console.print(env_text)
        return 0

    atomic_write(repo_root / ".env", env_text)
    ui.success("Wrote .env")

    shell = DockerShell()
    compose_file = str(repo_root / "install" / "docker-compose.yml")

    def _login() -> CommandResult:
        import getpass

        ui.info("Registry requires authentication.")
        user = cfg.github_user or input("GitHub username: ")
        token = cfg.github_token or getpass.getpass("GitHub token: ")
        return shell.login("ghcr.io", user, token)

    ui.info("Pulling images and starting the stack...")
    if not launch_stack(shell, compose_file, compose_profiles, registry_login=_login):
        ui.error("Stack failed to start. Check `docker compose logs`.")
        return 1
    ui.success("Stack started.")
    return 0
