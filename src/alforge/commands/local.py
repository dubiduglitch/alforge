"""``uninstall`` and ``purge`` - taking an installed thing back off the system.

Both kinds are handled here: a ``.deb`` goes through ``apt-get``, an AppImage is
simply deleted (image, launch link, menu entry, icon) with no privilege needed.
"""

from __future__ import annotations

from .. import appimage, deb, ui
from ..assets import KIND_APPIMAGE, KIND_DEB
from ..report import select_target


def _identity(context, name: str):  # noqa: ANN001, ANN201
    """Resolve a user supplied name to (kind, identity, target).

    *identity* is the Debian package name for a ``.deb`` and the alforge app id
    for an AppImage.  When the name is not tracked we fall back to treating it as
    a literal Debian package name, exactly as before.
    """
    try:
        target = select_target(context, name)
    except Exception:  # noqa: BLE001 - fall back to the literal name
        return KIND_DEB, name, None
    entry = context.state.get(str(target))
    return entry.kind or KIND_DEB, entry.package or target.name, target


def _remove(context, name: str) -> None:  # noqa: ANN001
    """Remove the installed artifact, keeping the repository tracked."""
    kind, identity, _target = _identity(context, name)
    if kind == KIND_APPIMAGE:
        if not appimage.is_installed(identity):
            ui.warn(f"{identity} is not installed")
            return
        if not ui.confirm(f"Remove {identity}?", default=False):
            ui.info("aborted")
            return
        removed = appimage.remove(identity, dry_run=context.dry_run)
        if context.dry_run:
            ui.info("would remove: " + ", ".join(removed))
        else:
            ui.ok(
                f"removed {identity} (still tracked, use 'alforge remove {name}' to stop tracking)"
            )
        return

    if deb.installed_version(identity) is None:
        ui.warn(f"{identity} is not installed")
        return
    if not ui.confirm(f"Remove the package {identity}?", default=False):
        ui.info("aborted")
        return
    command = deb.remove_package(identity, purge=False, dry_run=context.dry_run)
    if context.dry_run:
        ui.info("would run: " + " ".join(command))
    else:
        ui.ok(f"removed {identity} (still tracked, use 'alforge remove {name}' to stop tracking)")


def cmd_uninstall(context, args) -> int:
    for name in args.names:
        _remove(context, name)
    return 0


def cmd_purge(context, args) -> int:
    for name in args.names:
        kind, identity, target = _identity(context, name)
        if not ui.confirm(f"Purge {identity} and stop tracking it?", default=False):
            ui.info("aborted")
            continue
        if kind == KIND_APPIMAGE:
            if appimage.is_installed(identity):
                removed = appimage.remove(identity, dry_run=context.dry_run)
                if context.dry_run:
                    ui.info("would remove: " + ", ".join(removed))
            else:
                ui.detail(f"{identity} was not installed")
        elif deb.installed_version(identity) is not None:
            command = deb.remove_package(identity, purge=True, dry_run=context.dry_run)
            if context.dry_run:
                ui.info("would run: " + " ".join(command))
        else:
            ui.detail(f"{identity} was not installed")
        if target is not None and not context.dry_run:
            context.registry.remove(target)
            context.state.drop(str(target))
            ui.ok(f"purged {identity} and stopped tracking {target}")
        context.save_state()
    return 0
