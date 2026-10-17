"""Machine managed state: what we have seen and what we installed.

Kept out of ``repos.txt`` on purpose.  ``state.json`` answers two questions:

1. Has the upstream release changed since the last time we looked?  (cheap check
   based on the release tag plus the asset name/id, no download involved)
2. Which Debian package did this repository install, and at which version?
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import paths

STATE_VERSION = 1


@dataclass
class EntryState:
    package: str | None = None
    installed_version: str | None = None
    last_tag: str | None = None
    last_asset: str | None = None
    last_asset_url: str | None = None
    last_version: str | None = None
    last_sha256: str | None = None
    checked_at: str | None = None
    upgraded_at: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        data = dict(self.raw)
        data.update(
            {
                key: value
                for key, value in {
                    "package": self.package,
                    "installed_version": self.installed_version,
                    "last_tag": self.last_tag,
                    "last_asset": self.last_asset,
                    "last_asset_url": self.last_asset_url,
                    "last_version": self.last_version,
                    "last_sha256": self.last_sha256,
                    "checked_at": self.checked_at,
                    "upgraded_at": self.upgraded_at,
                }.items()
                if value is not None
            }
        )
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EntryState":
        known = {
            "package",
            "installed_version",
            "last_tag",
            "last_asset",
            "last_asset_url",
            "last_version",
            "last_sha256",
            "checked_at",
            "upgraded_at",
        }
        return cls(
            package=data.get("package"),
            installed_version=data.get("installed_version"),
            last_tag=data.get("last_tag"),
            last_asset=data.get("last_asset"),
            last_asset_url=data.get("last_asset_url"),
            last_version=data.get("last_version"),
            last_sha256=data.get("last_sha256"),
            checked_at=data.get("checked_at"),
            upgraded_at=data.get("upgraded_at"),
            raw={key: value for key, value in data.items() if key not in known},
        )


class State:
    def __init__(self, path: Path | None = None, *, data: dict[str, EntryState] | None = None) -> None:
        self.path = path or paths.state_file()
        self.entries: dict[str, EntryState] = data or {}

    @classmethod
    def load(cls, path: Path | None = None) -> "State":
        state_path = path or paths.state_file()
        if not state_path.exists():
            return cls(path=state_path)
        try:
            raw = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # Corrupt state is never fatal: it is a cache, rebuild it.
            return cls(path=state_path)
        entries = {
            str(key): EntryState.from_dict(value)
            for key, value in (raw.get("entries") or {}).items()
            if isinstance(value, dict)
        }
        return cls(path=state_path, data=entries)

    def get(self, key: str) -> EntryState:
        return self.entries.setdefault(key, EntryState())

    def drop(self, key: str) -> None:
        self.entries.pop(key, None)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": STATE_VERSION,
            "entries": {key: entry.as_dict() for key, entry in sorted(self.entries.items())},
        }
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.chmod(0o600)
        os.replace(tmp, self.path)
