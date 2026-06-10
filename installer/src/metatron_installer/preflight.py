from __future__ import annotations

import platform
import re
import socket
from collections.abc import Callable
from dataclasses import dataclass

# Host ports published by install/docker-compose.yml -> service.
PUBLISHED_PORTS: dict[int, str] = {
    5433: "postgres",
    6335: "qdrant",
    6336: "qdrant-grpc",
    7475: "neo4j-http",
    7688: "neo4j-bolt",
    8000: "metatron-api",
    8001: "embedding-proxy",
    8080: "splade",
    6379: "redis",
    3000: "metatron-ui",
    3001: "metatron-ui-cc",
    3080: "open-webui",
    11435: "ollama",
}

_VERSION_RE = re.compile(r"Docker version (?P<major>\d+)\.(?P<minor>\d+)")


@dataclass(frozen=True)
class DockerInfo:
    present: bool
    major: int = 0
    minor: int = 0


@dataclass(frozen=True)
class PortConflict:
    port: int
    service: str


def detect_os() -> str:
    return platform.system().lower()  # "linux" | "darwin" | "windows"


def parse_docker_version(output: str) -> DockerInfo:
    m = _VERSION_RE.search(output or "")
    if not m:
        return DockerInfo(present=False)
    return DockerInfo(present=True, major=int(m["major"]), minor=int(m["minor"]))


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.0)
        try:
            return s.connect_ex(("127.0.0.1", port)) == 0
        except OSError:
            return False


def find_port_conflicts(
    checker: Callable[[int], bool] = _port_in_use,
) -> list[PortConflict]:
    return [
        PortConflict(port=p, service=svc)
        for p, svc in PUBLISHED_PORTS.items()
        if checker(p)
    ]
