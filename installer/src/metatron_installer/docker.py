from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass

_AUTH_MARKERS = ("401", "denied", "unauthorized", "forbidden", "403")


@dataclass
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


def _default_runner(argv: list[str], env: dict[str, str] | None = None) -> CommandResult:
    proc = subprocess.run(argv, capture_output=True, text=True, env=env)
    return CommandResult(proc.returncode, proc.stdout, proc.stderr)


Runner = Callable[[list[str], dict[str, str] | None], CommandResult]


class DockerShell:
    def __init__(self, runner: Runner = _default_runner):
        self._run = runner

    def version(self) -> CommandResult:
        return self._run(["docker", "version", "--format", "{{.Server.Version}}"], None)

    def login(self, registry: str, user: str, token: str) -> CommandResult:
        # SECURITY: token is on argv (visible in `ps`) — acceptable for a local
        # single-user install. If reused server-side/CI, switch to --password-stdin.
        return self._run(["docker", "login", registry, "-u", user, "-p", token], None)

    def compose_pull(
        self,
        compose_file: str,
        env: dict[str, str],
        registry_login: Callable[[], CommandResult] | None,
    ) -> bool:
        argv = ["docker", "compose", "-f", compose_file, "pull"]
        res = self._run(argv, env)
        if res.returncode == 0:
            return True
        if registry_login and self._looks_like_auth_error(res.stderr):
            login_res = registry_login()
            if login_res.returncode != 0:
                return False
            return self._run(argv, env).returncode == 0
        return False

    def compose_up(self, compose_file: str, env: dict[str, str]) -> CommandResult:
        return self._run(["docker", "compose", "-f", compose_file, "up", "-d"], env)

    def compose_ps(self, compose_file: str, env: dict[str, str]) -> CommandResult:
        return self._run(
            ["docker", "compose", "-f", compose_file, "ps", "--format", "json"], env
        )

    def logs_tail(self, container: str, lines: int = 40) -> CommandResult:
        return self._run(["docker", "logs", "--tail", str(lines), container], None)

    @staticmethod
    def _looks_like_auth_error(stderr: str) -> bool:
        low = (stderr or "").lower()
        return any(marker in low for marker in _AUTH_MARKERS)
