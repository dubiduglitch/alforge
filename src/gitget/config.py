"""Configuration (tokens, settings) and the tracking registry.

Two files, two very different audiences:

``config.json``
    Machine managed, ``0600``, written by ``gitget setup``.  Tokens live here.

``repos.txt``
    Human managed.  One target per line, ``#`` starts a comment.  This is the
    file you edit by hand or append to with ``gitget add``.  gitget never
    writes learned data into it.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from . import paths
from .errors import ConfigError

CONFIG_VERSION = 1

DEFAULT_SETTINGS: dict[str, object] = {
    "default_forge": "github",
    "asset_exclude": ["-dbg", "-dev", "-doc", "-source", ".buildinfo", "dbgsym"],
    "require_checksum": False,
    "install_recommends": True,
}

SUPPORTED_FORGES = ("github", "gitlab", "codeberg", "gitea")


# --------------------------------------------------------------------------- #
# config.json
# --------------------------------------------------------------------------- #
@dataclass
class Config:
    tokens: dict[str, str] = field(default_factory=dict)
    settings: dict[str, object] = field(default_factory=lambda: dict(DEFAULT_SETTINGS))
    path: Path = field(default_factory=paths.config_file)

    def token(self, forge: str) -> str | None:
        value = self.tokens.get(forge, "").strip()
        return value or None

    def setting(self, key: str, default: object = None) -> object:
        return self.settings.get(key, DEFAULT_SETTINGS.get(key, default))

    def as_dict(self) -> dict[str, object]:
        return {"version": CONFIG_VERSION, "tokens": self.tokens, "settings": self.settings}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.as_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.chmod(0o600)
        os.replace(tmp, self.path)
        self.path.chmod(0o600)


def load_config(path: Path | None = None) -> Config:
    config_path = path or paths.config_file()
    if not config_path.exists():
        return Config(path=config_path)
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"cannot read {config_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{config_path}: expected a JSON object")
    tokens = {str(k): str(v) for k, v in (raw.get("tokens") or {}).items() if v}
    settings = dict(DEFAULT_SETTINGS)
    settings.update(raw.get("settings") or {})
    return Config(tokens=tokens, settings=settings, path=config_path)


def insecure_permissions(path: Path | None = None) -> bool:
    """True when the token file is group/world readable."""
    config_path = path or paths.config_file()
    if not config_path.exists():
        return False
    return bool(config_path.stat().st_mode & 0o077)


# --------------------------------------------------------------------------- #
# targets: "[forge:]owner/repo" with forge-specific path shapes
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Target:
    """A tracked upstream repository."""

    forge: str
    path: str

    def __str__(self) -> str:
        return f"{self.forge}:{self.path}"

    @property
    def name(self) -> str:
        """Last path segment: the human friendly short name."""
        return self.path.rstrip("/").split("/")[-1]

    @property
    def key(self) -> str:
        return str(self)


def parse_target(raw: str, *, default_forge: str = "github") -> Target:
    """Parse ``forge:path`` or a bare ``owner/repo`` (default forge)."""
    value = raw.strip()
    if not value:
        raise ConfigError("empty target")
    if ":" in value.split("/")[0]:
        forge, _, path = value.partition(":")
        forge = forge.lower()
        canonical = {"forgejo": "gitea", "codeberg.org": "codeberg"}.get(forge, forge)
        if canonical not in SUPPORTED_FORGES:
            raise ConfigError(
                f"unknown forge {forge!r}",
                hint=f"supported forges: {', '.join(SUPPORTED_FORGES)}",
            )
        if not path:
            raise ConfigError(f"target {raw!r} has no repository path")
        return Target(canonical, path.strip("/"))
    return Target(default_forge, value.strip("/"))


def short_name_matches(target: Target, needle: str) -> bool:
    """Loose match used by ``remove``/``uninstall`` style commands."""
    needle = needle.strip().lower()
    if not needle:
        return False
    return (
        target.name.lower() == needle
        or target.path.lower() == needle
        or str(target).lower() == needle
        or target.path.lower().endswith("/" + needle)
    )


# --------------------------------------------------------------------------- #
# repos.txt
# --------------------------------------------------------------------------- #
def _normalise_line(line: str) -> str:
    return line.split("#", 1)[0].strip()


class Registry:
    """Line oriented view of ``repos.txt`` that preserves comments and order."""

    def __init__(self, path: Path | None = None, *, default_forge: str = "github") -> None:
        self.path = path or paths.registry_file()
        self.default_forge = default_forge
        self._lines: list[str] = []
        self._targets: list[Target] = []

    def load(self) -> "Registry":
        self._lines = []
        self._targets = []
        if not self.path.exists():
            return self
        try:
            content = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ConfigError(f"cannot read {self.path}: {exc}") from exc
        for number, line in enumerate(content.splitlines(), start=1):
            self._lines.append(line)
            stripped = _normalise_line(line)
            if not stripped:
                continue
            try:
                self._targets.append(parse_target(stripped, default_forge=self.default_forge))
            except ConfigError as exc:
                raise ConfigError(f"{self.path}:{number}: {exc}") from exc
        return self

    @property
    def targets(self) -> list[Target]:
        return list(self._targets)

    def __iter__(self) -> Iterable[Target]:
        return iter(self._targets)

    def __len__(self) -> int:
        return len(self._targets)

    def find(self, needle: str) -> list[Target]:
        return [target for target in self._targets if short_name_matches(target, needle)]

    def add(self, target: Target) -> bool:
        """Append a target. Returns False when it was already tracked."""
        if any(str(existing) == str(target) for existing in self._targets):
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        block = ""
        if not self._lines:
            block += (
                "# gitget tracking registry - one target per line.\n"
                "# format: [forge:]path\n"
                "#   github:owner/repo\n"
                "#   gitlab:group/project\n"
                "#   codeberg:owner/repo\n"
                "#   gitea:git.example.org/owner/repo\n"
                "\n"
            )
        block += f"{target}\n"
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(block)
        self._targets.append(target)
        self._lines = self.path.read_text(encoding="utf-8").splitlines()
        return True

    def remove(self, target: Target) -> bool:
        """Remove a target, keeping every comment and blank line intact."""
        if not self.path.exists():
            return False
        needle = str(target)
        kept: list[str] = []
        removed = False
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if _normalise_line(line) == needle:
                removed = True
                continue
            kept.append(line)
        if not removed:
            return False
        body = "\n".join(kept).rstrip("\n") + "\n"
        tmp = self.path.with_suffix(".txt.tmp")
        tmp.write_text(body, encoding="utf-8")
        os.replace(tmp, self.path)
        self.load()
        return True
