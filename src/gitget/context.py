"""Shared runtime context: config, registry, state and the HTTP client."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import paths
from .config import Config, Registry, load_config
from .http import HttpClient
from .providers import Provider, get_provider
from .state import State


@dataclass
class Context:
    config: Config
    registry: Registry
    state: State
    client: HttpClient
    dry_run: bool = False
    offline: bool = False

    @classmethod
    def create(cls, *, dry_run: bool = False, offline: bool = False) -> "Context":
        config = load_config()
        registry = Registry(default_forge=str(config.setting("default_forge", "github"))).load()
        state = State.load()
        client = HttpClient(config.tokens)
        return cls(
            config=config,
            registry=registry,
            state=state,
            client=client,
            dry_run=dry_run,
            offline=offline,
        )

    # -- convenience ------------------------------------------------------ #
    def provider(self, forge: str) -> Provider:
        return get_provider(forge, self.client)

    def asset_exclude(self) -> tuple[str, ...]:
        value = self.config.setting("asset_exclude", [])
        if isinstance(value, str):
            return (value,)
        return tuple(str(item) for item in value or [])

    def require_checksum(self, override: bool | None = None) -> bool:
        if override is not None:
            return override
        return bool(self.config.setting("require_checksum", False))

    def save_state(self) -> None:
        if self.dry_run:
            return
        self.state.save()

    def download_dir(self) -> Path:
        directory = paths.download_dir()
        directory.mkdir(parents=True, exist_ok=True)
        return directory
