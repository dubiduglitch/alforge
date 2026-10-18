"""``install``, ``update`` and ``upgrade`` - the network facing commands."""

from __future__ import annotations

import os
from pathlib import Path

from .. import deb, installer, ui
from ..config import Target
from ..errors import AlforgeError, NotFoundError
from ..records import record_check, record_download, record_install
from ..report import build_rows, filter_targets, render
from ..targets import resolve


def _exit_code(exc: Exception) -> int:
    return getattr(exc, "exit_code", 1)


def _kind(args) -> str | None:  # noqa: ANN001
    """``--kind auto`` means "let the release decide"."""
    value = getattr(args, "kind", None)
    return None if value in (None, "auto") else value


def cmd_install(context, args) -> int:
    target = resolve(context, args.spec, forge=args.forge)

    if args.spec.startswith(("http://", "https://")) and not _is_forge_url(context, args.spec):
        return _install_direct(context, args.spec)

    plan, artifact, info, digest = installer.run(
        context,
        target,
        asset_filter=args.asset,
        kind=_kind(args),
        force=args.force,
        download_only=args.download_only,
        recommend=bool(context.config.setting("install_recommends", True)),
        require_checksum=args.require_checksum,
        allow_prerelease=args.allow_prerelease,
    )
    if info is None:
        record_check(context, target, plan)
    elif args.download_only:
        record_download(
            context, target, plan, package=info.name, version=info.version, digest=digest
        )
    else:
        record_install(
            context, target, plan, package=info.name, version=info.version, digest=digest
        )
    if not context.dry_run and context.registry.add(target):
        ui.detail(f"added {target} to the tracking registry")
    context.save_state()
    if args.download_only and info is not None:
        ui.ok(f"saved to {artifact}")
    return 0


def _is_forge_url(context, url: str) -> bool:  # noqa: ANN001
    from ..providers import detect_url

    return detect_url(url, context.client) is not None


def _install_direct(context, url: str) -> int:
    ui.warn("this URL is not a known forge repository: the package cannot be tracked")
    ui.warn("it will be installed once, without automatic updates")
    if not ui.confirm("Continue?", default=False):
        ui.info("aborted")
        return 1
    directory = context.download_dir()
    destination = Path(directory) / (url.rsplit("/", 1)[-1] or "artifact.deb")
    if context.dry_run:
        ui.info(f"would download {url} to {destination} and install it")
        return 0
    with destination.open("wb") as sink:
        context.client.download(url, sink.write)
    if destination.suffix != ".deb":
        raise NotFoundError(
            "only .deb artifacts can be installed from a bare URL",
            hint="for an AppImage, install through its repository so it can be tracked",
        )
    info = deb.package_info(destination)
    deb.install_local(destination, dry_run=context.dry_run)
    ui.ok(f"installed {info.name} {info.version} (not tracked)")
    return 0


def cmd_update(context, args) -> int:
    """Refresh what the forges publish, like ``apt update``."""
    if context.offline:
        raise AlforgeError(
            "'alforge update' needs network access",
            hint="drop --offline; use 'alforge list' to see cached information",
        )
    targets = filter_targets(context, getattr(args, "specs", None) or None)
    if not targets:
        ui.info("nothing tracked yet: 'alforge add owner/repo'")
        return 0

    failed = 0
    for target in targets:
        try:
            candidate = installer.plan(context, target)
            record_check(context, target, candidate)
        except Exception as exc:  # noqa: BLE001 - one bad repo must not stop the rest
            ui.error(f"{target}: {exc}")
            failed = max(failed, _exit_code(exc))
            record_check(context, target, None)
            continue
    context.save_state()
    rows = build_rows(context, targets)
    render(rows)
    return failed


def cmd_upgrade(context, args) -> int:
    """Install newer versions of tracked packages."""
    targets = filter_targets(context, getattr(args, "specs", None) or None)
    if not targets:
        ui.info("nothing tracked yet: 'alforge add owner/repo'")
        return 0

    failed = 0
    upgraded = 0
    for target in targets:
        try:
            ui.heading(str(target))
            plan, artifact, info, digest = installer.run(
                context,
                target,
                asset_filter=args.asset,
                kind=_kind(args),
                force=args.force,
                download_only=args.download_only,
                recommend=bool(context.config.setting("install_recommends", True)),
                require_checksum=args.require_checksum,
                allow_prerelease=args.allow_prerelease,
            )
            if info is None:
                record_check(context, target, plan)
            elif args.download_only:
                record_download(
                    context, target, plan, package=info.name, version=info.version, digest=digest
                )
            else:
                record_install(
                    context, target, plan, package=info.name, version=info.version, digest=digest
                )
                upgraded += 1
                if not context.dry_run:
                    ui.ok(f"{target}: installed {info.name} {info.version}")
        except Exception as exc:  # noqa: BLE001 - one bad repo must not stop the rest
            ui.error(f"{target}: {exc}")
            failed = max(failed, _exit_code(exc))
    context.save_state()
    if upgraded:
        ui.info(f"{upgraded} package(s) upgraded")
    if getattr(args, "notify", False):
        _notify(upgraded)
    return failed


def _notify(upgraded: int) -> None:
    import shutil
    import subprocess

    notify_send = shutil.which("notify-send")
    if not notify_send:
        return
    if upgraded:
        summary = f"alforge upgraded {upgraded} package(s)"
    else:
        summary = "alforge: everything is up to date"
    environment = dict(os.environ)
    try:
        subprocess.run(
            [notify_send, "-a", "alforge", "alforge", summary],
            check=False,
            env=environment,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        pass
