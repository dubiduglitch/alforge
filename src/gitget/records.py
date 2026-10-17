"""Writing learned facts back into the state file."""

from __future__ import annotations

from datetime import datetime, timezone

from . import deb, ui
from .config import Target
from .installer import Plan


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def record_check(context, target: Target, candidate: Plan | None) -> None:  # noqa: ANN001
    """Remember what the forge currently publishes for *target*."""
    entry = context.state.get(str(target))
    entry.checked_at = _now()
    if candidate is not None:
        entry.last_tag = candidate.release.tag
        entry.last_asset = candidate.asset.name
        entry.last_asset_url = candidate.asset.url
    if entry.package:
        entry.installed_version = deb.installed_version(entry.package)


def record_install(
    context,  # noqa: ANN001
    target: Target,
    candidate: Plan,
    *,
    package: str,
    version: str,
    digest: str | None,
) -> None:
    """Remember a successful installation."""
    entry = context.state.get(str(target))
    entry.package = package
    entry.last_tag = candidate.release.tag
    entry.last_asset = candidate.asset.name
    entry.last_asset_url = candidate.asset.url
    entry.last_version = version
    entry.installed_version = deb.installed_version(package) or version
    entry.upgraded_at = _now()
    entry.checked_at = _now()
    if digest:
        entry.last_sha256 = digest


def forget(context, target: Target) -> None:  # noqa: ANN001
    context.state.drop(str(target))
