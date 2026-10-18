"""The install pipeline: plan -> download -> verify -> install.

Kept separate from the commands so that ``install`` and ``upgrade`` share
exactly one code path.  Every step is explicit and testable, and the privileged
one is a single ``apt-get`` call at the end.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from . import appimage, assets as asset_selection
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
    kind: str = asset_selection.KIND_DEB

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
            "Several assets match equally well:",
            [f"{candidate.asset.name}  [{candidate.score}]" for candidate in candidates],
        )
        if index is None:
            return None
        return candidates[index]

    return pick


def _select_asset(
    context,  # noqa: ANN001 - Context
    candidates,  # noqa: ANN001 - tuple[Asset, ...]
    *,
    requested: str | None,
    hint: str,
    picker,  # noqa: ANN001
) -> asset_selection.Candidate:
    """Pick an asset, preferring ``.deb`` and falling back to AppImage.

    An explicit *requested* kind (from ``--kind`` or the state of an already
    tracked repository) is honoured strictly.  Otherwise ``.deb`` is tried
    first, because it is the format that goes through the system's package
    manager, and an AppImage is used only when no ``.deb`` fits.
    """
    exclude = context.asset_exclude()
    if requested:
        return asset_selection.select(
            candidates, kind=requested, hint=hint, exclude=exclude, picker=picker
        )
    try:
        return asset_selection.select(
            candidates, kind=asset_selection.KIND_DEB, hint=hint, exclude=exclude, picker=picker
        )
    except NotFoundError as no_deb:
        try:
            return asset_selection.select(
                candidates,
                kind=asset_selection.KIND_APPIMAGE,
                hint=hint,
                exclude=exclude,
                picker=picker,
            )
        except NotFoundError:
            raise no_deb from None


def plan(
    context,  # noqa: ANN001 - Context
    target: Target,
    *,
    asset_filter: str | None = None,
    allow_prerelease: bool = False,
    kind: str | None = None,
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
        stable = provider.latest_stable_release(target.path)
        if stable is not None and stable.tag != release.tag:
            ui.detail(
                f"{target}: skipping pre-release {release.tag} in favour of {stable.tag}"
            )
            release = stable
        elif stable is None:
            ui.warn(
                f"{target}: only pre-releases are published, using {release.tag}"
            )
            ui.detail("pass --allow-prerelease to silence this warning")
        else:
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
    entry = context.state.get(str(target))
    chosen = _select_asset(
        context,
        candidates,
        requested=kind or entry.kind,
        hint=target.name,
        picker=picker,
    )
    if chosen.reasons:
        ui.detail(f"selected {chosen.asset.name} ({', '.join(chosen.reasons)})")
    resolved = kind or entry.kind
    if not resolved:
        resolved = (
            asset_selection.KIND_APPIMAGE
            if appimage.is_appimage_asset(chosen.asset.name)
            else asset_selection.KIND_DEB
        )
    return Plan(target=target, release=release, asset=chosen.asset, kind=resolved)


# --------------------------------------------------------------------------- #
# change detection
# --------------------------------------------------------------------------- #
def installed_version_of(kind: str, identity: str | None) -> str | None:
    """Installed version of a tracked thing, whichever kind it is.

    ``identity`` is a Debian package name for ``.deb`` and an alforge app id for
    an AppImage.
    """
    if not identity:
        return None
    if kind == asset_selection.KIND_APPIMAGE:
        return appimage.installed_version(identity)
    return deb.installed_version(identity)


def up_to_date(context, candidate: Plan) -> bool:  # noqa: ANN001 - Context
    """Cheap check: has anything changed since the last successful upgrade?

    No download is involved.  A package that was removed by hand counts as out
    of date, so ``alforge upgrade`` reinstalls it, which is what people expect
    from a tool that tracks a release.
    """
    entry = context.state.get(str(candidate.target))
    identity = entry.package
    if not identity or not entry.last_version:
        return False
    if entry.last_tag != candidate.release.tag:
        return False
    if entry.last_asset != candidate.asset.name:
        return False
    installed = installed_version_of(candidate.kind, identity)
    if installed is None and candidate.kind == asset_selection.KIND_APPIMAGE:
        # The image is still there but its name no longer carries a version;
        # fall back to what alforge recorded when it installed it.
        if appimage.is_installed(identity):
            installed = entry.last_version
    if installed is None:
        return False
    from .versions import compare

    return compare(installed, entry.last_version) >= 0


# --------------------------------------------------------------------------- #
# download
# --------------------------------------------------------------------------- #
def _cache_slug(candidate: Plan) -> str:
    """Filesystem-safe per-target prefix for cache file names."""
    return re.sub(r"[^a-z0-9]+", "-", str(candidate.target).lower()).strip("-")


def artifact_suffix(kind: str) -> str:
    """Extension of the artifact we cache for *kind*."""
    return ".AppImage" if kind == asset_selection.KIND_APPIMAGE else ".deb"


def cached_path(context, candidate: Plan) -> Path:  # noqa: ANN001 - Context
    """Deterministic cache location of the exact artifact a plan describes."""
    ident = re.sub(r"[^A-Za-z0-9._-]+", "-", candidate.asset_id).strip("-")
    suffix = artifact_suffix(candidate.kind)
    return context.download_dir() / f"{_cache_slug(candidate)}--{ident}{suffix}"


def _prune_cache(context, candidate: Plan, *, keep: Path) -> None:  # noqa: ANN001
    """Drop older artifacts for the same target so the cache cannot grow forever."""
    for stale in context.download_dir().glob(
        f"{_cache_slug(candidate)}--*{artifact_suffix(candidate.kind)}"
    ):
        if stale != keep:
            stale.unlink(missing_ok=True)


def download(context, candidate: Plan) -> Path:  # noqa: ANN001 - Context
    """Fetch the artifact into the cache, reusing a previous download.

    ``--download-only`` runs (and the timer in download mode) would otherwise
    fetch the same file on every invocation; because the file name is derived
    from the asset id, an unchanged release is reused as-is.
    """
    destination = cached_path(context, candidate)
    if destination.exists() and destination.stat().st_size > 0:
        ui.detail(f"reusing cached {destination.name}")
        return destination

    ui.info(
        f"downloading {candidate.asset.name}{_size_label(candidate.asset.size)} "
        f"from {candidate.target}"
    )
    partial = destination.with_name(destination.name + ".part")
    try:
        with partial.open("wb") as sink:
            written = context.client.download(
                candidate.asset.url, sink.write, forge=candidate.target.forge
            )
        if written == 0:
            raise AlforgeError(f"empty download for {candidate.asset.name}")
        if candidate.asset.size and written != candidate.asset.size:
            ui.warn(
                f"size mismatch for {candidate.asset.name}: "
                f"expected {candidate.asset.size} bytes, got {written}"
            )
        os.replace(partial, destination)
        destination.chmod(0o600)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    _prune_cache(context, candidate, keep=destination)
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
    if require is None:
        # An AppImage is an unsigned executable blob, so a missing checksum is
        # treated as fatal unless the user explicitly opts out.  A .deb keeps
        # the historical default, which is to warn and continue.
        must = context.require_checksum(None) or candidate.kind == asset_selection.KIND_APPIMAGE
    else:
        must = require
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
def artifact_info(context, candidate: Plan, path: Path):  # noqa: ANN001, ANN201
    """Read name and version out of a downloaded artifact, per kind."""
    if candidate.kind == asset_selection.KIND_APPIMAGE:
        return appimage.probe(
            path,
            app_id=appimage.app_id(candidate.target),
            fallback_version=candidate.release.tag,
        )
    return deb.package_info(path)


def local_install(
    context,  # noqa: ANN001 - Context
    candidate: Plan,
    path: Path,
    *,
    info=None,  # noqa: ANN001 - deb.PackageInfo | appimage.AppImageInfo
    recommend: bool = True,
):
    """Validate the artifact and hand it to whichever tool installs it."""
    if candidate.kind == asset_selection.KIND_APPIMAGE:
        info = info or artifact_info(context, candidate, path)
        other = conflicting_target(context, candidate.target, info.name)
        if other is not None:
            raise AlforgeError(
                f"{info.name} is already tracked through {other}",
                hint=f"two repositories would manage the same application; "
                f"stop tracking one first: 'alforge remove {other}'",
            )
        ui.info(f"installing {info.name} {info.version}")
        return appimage.install(context, candidate.target, path, info)

    info = info or deb.package_info(path)
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
    command = deb.install_local(path, recommend=recommend, dry_run=context.dry_run)
    if context.dry_run:
        ui.info("would run: " + " ".join(command))
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
    candidate: Plan | None = None,
    asset_filter: str | None = None,
    kind: str | None = None,
    force: bool = False,
    download_only: bool = False,
    recommend: bool = True,
    require_checksum: bool | None = None,
    allow_prerelease: bool = False,
):
    """Full pipeline for one target.

    Returns (plan, artifact path, package info, verified sha256).  ``package
    info`` is None only when the target was already up to date and nothing ran;
    in ``download_only`` mode it is the metadata read from the artifact.

    Pass *candidate* to reuse a plan that was already computed (the ``alforge://``
    handler shows its details before asking, so it plans once).
    """
    if candidate is None:
        candidate = plan(
            context,
            target,
            asset_filter=asset_filter,
            allow_prerelease=allow_prerelease,
            kind=kind,
        )
    entry = context.state.get(str(target))

    if not force and up_to_date(context, candidate):
        ui.ok(f"{target} is up to date ({entry.last_version})")
        return candidate, Path(), None, entry.last_sha256

    path = download(context, candidate)
    digest = verify(context, candidate, path, require=require_checksum)
    info = artifact_info(context, candidate, path)
    if download_only:
        ui.ok(f"downloaded to {path} (not installed)")
        return candidate, path, info, digest
    try:
        local_install(context, candidate, path, info=info, recommend=recommend)
    finally:
        path.unlink(missing_ok=True)
    return candidate, path, info, digest
