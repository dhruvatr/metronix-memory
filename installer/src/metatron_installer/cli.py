from __future__ import annotations

import argparse

from . import __version__


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="metatron-installer")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--config", help="Path to a non-interactive answers YAML")
    p.add_argument("--non-interactive", action="store_true")
    p.add_argument("--dry-run", action="store_true", help="Render artifacts, do not launch Docker")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    # Real dispatch wired in Task 11; for now just succeed.
    _ = args
    return 0
