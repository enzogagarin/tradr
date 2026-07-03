from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def default_audit_path() -> Path:
    return Path("data/audit/paper-decisions.jsonl")


class AuditLog:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else default_audit_path()

    def append(self, event: dict[str, Any]) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")
        return self.path

    def tail(self, limit: int = 10) -> list[dict[str, Any]]:
        if limit <= 0 or not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines[-limit:] if line.strip()]
