from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

_KEY_RE = re.compile(r"^(?P<key>[A-Za-z_][A-Za-z0-9_]*)=")


def merge_env(template: str, overrides: dict[str, str]) -> str:
    """Replace KEY= lines in place; append keys not present. Comments untouched."""
    remaining = dict(overrides)
    out_lines: list[str] = []
    for line in template.splitlines():
        m = _KEY_RE.match(line)
        if m and m.group("key") in remaining:
            key = m.group("key")
            out_lines.append(f"{key}={remaining.pop(key)}")
        else:
            out_lines.append(line)
    for key, value in remaining.items():
        out_lines.append(f"{key}={value}")
    return "\n".join(out_lines) + "\n"


def atomic_write(target: Path, content: str) -> None:
    """Write via temp file + os.replace so an interrupted write never leaves a partial .env."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=".env.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(content)
        os.replace(tmp, target)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
