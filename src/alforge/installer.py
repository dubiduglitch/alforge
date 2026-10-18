"""The install pipeline: plan -> download -> verify -> install.

Kept separate from the commands so that ``install`` and ``upgrade`` share
exactly one code path.  Every step is explicit and testable, and the privileged
one is a single ``apt-get`` call at the end.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import assets as asset_selection
from . import checksum, deb, ui
from .config import Target
from .errors import ChecksumError, AlforgeError, NotFoundError, UsageError
from .providers import Asset, Release


@dataclass
class Plan:
    """What we intend to install for a target."""

    target: Target
    release: Release
    asset: Asset

    @property
    def asset_id(self) -> str:
        """Stable identifier of the exact artifact, used for change detection."""
        return self.asset.id or f"{self.asset.name}:{self.asset.size or 0}"

    def describe(self) -> str:
        return f"{self.target} {self.release.tag or '?'} -> {self.asset.name}"


def _size_label(size: int | None) -> str:
    if not size:
        return ""
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return f" ({value:.1f} {unit})" if unit != "B" else f" ({int(value)} B)"
        value /= 1024
    return ""


def _picker_for_tied_assets() -> object:
    def pick(candidates):  # noqa: ANN001
        index = ui.choose(
            "Several .deb assets match equally well:",
            [f"{candidate.asset.name}  [{candidate.score}]" for candidate in candidates],
        )
        if index is None:
            return None
        return candidates[index]

    return pick


def plan(
    context,  # noqa: ANN001 - Context
    target: Target,
    *,
    asset_filter: str | None = None,
    allow_prerelease: bool = False,
) -> Plan:
    """Resolve the newest release asset worth installing for *target*."""
    if context.offline:
        raise UsageError(
            f"cannot resolve {target} in offline mode",
            hint="cached information is available through 'alforge list'",
        )
    provider = context.provider(target.forge)
    release = provider.latest_release(target.path)
    if release is None:
        raise NotFoundError(
            f"{target} publishes no release",
            hint="check the repository name, or that it really cuts releases",
        )
    if release.prerelease and not allow_prerelease:
        ui.warn(f"{target}: latest release {release.tag} is marked as a pre-release")

    candidates: tuple[Asset, ...] = release.assets
    if asset_filter:
        needle = asset_filter.lower()
        candidates = tuple(asset for asset in candidates if needle in asset.name.lower())
        if not candidates:
            raise NotFoundError(
                f"no asset matching {asset_filter!r} in {target} {release.tag}",
                hint=f"available: {', '.join(asset.name for asset in release.assets[:6])}",
            )

    picker = _picker_for_tied_assets() if ui.is_tty() else None
    chosen = asset_selection.select(
        candidates,
        hint=target.name,
        exclude=context.asset_exclude(),
        picker=picker,
    )
    if chosen.reasons:
        ui.detail(f"selected {chosen.asset.name} ({', '.join(chosen.reasons)})")
    return Plan(target=target, release=release, asset=chosen.asset)


# --------------------------------------------------------------------------- #
# change detection
# --------------------------------------------------------------------------- #
def up_to_date(context, candidate: Plan) -> bool:  # noqa: ANN001 - Context
    """Cheap check: has anything changed since the last successful upgrade?

    No download is involved.  A package that was removed by hand counts as out
    of date, so ``alforge upgrade`` reinstalls it, which is what people expect
    from a tool that tracks a release.
    """
    entry = context.state.get(str(candidate.target))
    package = entry.package
    if not package or not entry.last_version:
        return False
    if entry.last_tag != candidate.release.tag:
        return False
    if entry.last_asset != candidate.asset.name:
        return False
    installed = deb.installed_version(package)
    if installed is None:
        return False
    from .versions import compare

    return compare(installed, entry.last_version) >= 0


# --------------------------------------------------------------------------- #
# download
# --------------------------------------------------------------------------- #
def download(context, candidate: Plan) -> Path:  # noqa: ANN001 - Context
    directory = context.download_dir()
    handle, name = tempfile.mkstemp(prefix="alforge-", suffix=".deb", dir=directory)
    os.close(handle)
    destination = Path(name)
    ui.info(
        f"downloading {candidate.asset.name}{_size_label(candidate.asset.size)} "
        f"from {candidate.target}"
    )
    written = 0
    try:
        with destination.open("wb") as sink:
            written = context.client.download(
                candidate.asset.url, sink.write, forge=candidate.target.forge
            )
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    if written == 0:
        destination.unlink(missing_ok=True)
        raise AlforgeError(f"empty download for {candidate.asset.name}")
    if candidate.asset.size and written != candidate.asset.size:
        ui.warn(
            f"size mismatch for {candidate.asset.name}: "
            f"expected {candidate.asset.size} bytes, got {written}"
        )
    return destination


# --------------------------------------------------------------------------- #
# checksum verification
# --------------------------------------------------------------------------- #
def expected_digest(context, candidate: Plan) -> tuple[str | None, str | None]:  # noqa: ANN001
    """Return (sha256, source) from the asset digest or a published manifest."""
    digest = candidate.asset.digest
    if digest:
        _, _, value = digest.partition(":")
        if value:
            return value.lower(), f"asset digest ({candidate.asset.name})"
        if len(digest) == 64:
            return digest.lower(), f"asset digest ({candidate.asset.name})"

    manifest = next(
        (asset for asset in candidate.release.assets if checksum.is_manifest_name(asset.name)),
        None,
    )
    if manifest is None:
        return None, None
    ui.detail(f"checking against {manifest.name}")
    response = context.client.request(manifest.url, allow_404=True)
    if response.status != 200:
        ui.warn(f"could not download {manifest.name}, skipping verification")
        return None, None
    digests = checksum.parse_manifest(response.body.decode("utf-8", errors="replace"))
    for name in (candidate.asset.name, candidate.asset.url.rsplit("/", 1)[-1]):
        found = checksum.lookup(digests, name)
        if found:
            return found, manifest.name
    return None, None


def verify(context, candidate: Plan, path: Path, *, require: bool | None = None) -> str:
    """Verify *path*, returning the sha256 that was recorded."""
    expected, source = expected_digest(context, candidate)
    must = context.require_checksum(require)
    if expected:
        digest = checksum.verify(path, expected)
        ui.ok(f"checksum verified against {source}")
        return digest
    if must:
        raise ChecksumError(
            f"no checksum published for {candidate.asset.name}",
            hint="upstream publishes no SHA256SUMS/*.sha256 asset; "
            "install with --no-require-checksum to accept the risk",
        )
    ui.warn(
        f"no checksum published for {candidate.asset.name}, continuing unverified"
    )
    return checksum.sha256_file(path)


# --------------------------------------------------------------------------- #
# install
# --------------------------------------------------------------------------- #
def local_install(
    context,  # noqa: ANN001 - Context
    candidate: Plan,
    path: Path,
    *,
    recommend: bool = True,
) -> deb.PackageInfo:
    """Validate the artifact and hand it to apt."""
    info = deb.package_info(path)
    other = conflicting_target(context, candidate.target, info.name)
    if other is not None:
        raise AlforgeError(
            f"{info.name} is already tracked through {other}",
            hint=f"two repositories would manage the same package; "
            f"stop tracking one first: 'alforge remove {other}'",
        )
    machine = deb.system_arch()
    if info.architecture not in ("all", machine):
        raise AlforgeError(
            f"{candidate.asset.name} is built for {info.architecture}, this machine is {machine}",
            hint="the release naming may be ambiguous; use --asset to choose explicitly",
        )
    ui.info(f"installing {info.name} {info.version}")
    deb.install_local(path, recommend=recommend, dry_run=context.dry_run)
    return info


def conflicting_target(context, target: Target, package: str) -> str | None:  # noqa: ANN001
    """Another tracked target that already maps to *package*, if any."""
    for key, entry in context.state.entries.items():
        if key != str(target) and entry.package == package:
            return key
    return None


def run(
    context,  # noqa: ANN001 - Context
    target: Target,
    *,
    asset_filter: str | None = None,
    force: bool = False,
    download_only: bool = False,
    recommend: bool = True,
    require_checksum: bool | None = None,
) -> tuple[Plan, Path, deb.PackageInfo | None, str | None]:
    """Full pipeline for one target.

    Returns (plan, artifact path, installed package info, verified sha256).
    ``package info`` is None when ``download_only`` is set.
    """
    candidate = plan(context, target, asset_filter=asset_filter)

    if not force and up_to_date(context, candidate):
        entry = context.state.get(str(target))
        ui.ok(f"{target} is up to date ({entry.last_version})")
        return candidate, Path(), None, entry.last_sha256

    path = download(context, candidate)
    digest: str | None = None
    try:
        digest = verify(context, candidate, path, require=require_checksum)
        if download_only:
            ui.ok(f"downloaded to {path} (not installed)")
            return candidate, path, None, digest
        info = local_install(context, candidate, path, recommend=recommend)
    finally:
        if not download_only:
            path.unlink(missing_ok=True)
    return candidate, path, info, digest
