"""Writing learned facts back into the state file."""

from __future__ import annotations

from datetime import datetime, timezone

from . import ui
from .config import Target
from .installer import Plan, installed_version_of


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def record_check(context, target: Target, candidate: Plan | None) -> None:  # noqa: ANN001
    """Remember what the forge currently publishes for *target*."""
    entry = context.state.get(str(target))
    entry.checked_at = _now()
    if candidate is not None:
        entry.kind = candidate.kind
        entry.last_tag = candidate.release.tag
        entry.last_asset = candidate.asset.name
        entry.last_asset_url = candidate.asset.url
        # Extract version from tag (strip leading 'v' if present)
        tag = candidate.release.tag
        if tag.startswith("v"):
            tag = tag[1:]
        entry.last_version = tag
    if entry.package:
        entry.installed_version = installed_version_of(entry.kind, entry.package)


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
    entry.kind = candidate.kind
    entry.package = package
    entry.last_tag = candidate.release.tag
    entry.last_asset = candidate.asset.name
    entry.last_asset_url = candidate.asset.url
    entry.last_version = version
    entry.installed_version = installed_version_of(candidate.kind, package) or version
    entry.upgraded_at = _now()
    entry.checked_at = _now()
    if digest:
        entry.last_sha256 = digest


def record_download(
    context,  # noqa: ANN001
    target: Target,
    candidate: Plan,
    *,
    package: str,
    version: str,
    digest: str | None,
) -> None:
    """Remember an artifact that was fetched but deliberately not installed.

    The name/version come from the artifact itself, so ``list`` can report what
    is available even though nothing was installed, and the next run finds the
    artifact already in the cache.
    """
    entry = context.state.get(str(target))
    entry.kind = candidate.kind
    entry.package = package
    entry.last_tag = candidate.release.tag
    entry.last_asset = candidate.asset.name
    entry.last_asset_url = candidate.asset.url
    entry.last_version = version
    entry.installed_version = installed_version_of(candidate.kind, package)
    entry.checked_at = _now()
    if digest:
        entry.last_sha256 = digest


def forget(context, target: Target) -> None:  # noqa: ANN001
    context.state.drop(str(target))
