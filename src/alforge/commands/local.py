"""``uninstall`` and ``purge`` - removing packages from the system."""

from __future__ import annotations

from .. import deb, ui
from ..report import select_target


def _package_for(context, target, fallback: str) -> str:  # noqa: ANN001
    entry = context.state.get(str(target))
    return entry.package or fallback


def cmd_uninstall(context, args) -> int:
    failures = 0
    for name in args.names:
        try:
            target = select_target(context, name)
        except Exception:  # noqa: BLE001 - fall back to the literal package name
            target = None
        package = _package_for(context, target, name) if target else name
        if deb.installed_version(package) is None:
            ui.warn(f"{package} is not installed")
            continue
        if not ui.confirm(f"Remove the package {package}?", default=False):
            ui.info("aborted")
            continue
        command = deb.remove_package(package, purge=False, dry_run=context.dry_run)
        if context.dry_run:
            ui.info("would run: " + " ".join(command))
        else:
            ui.ok(f"removed {package} (still tracked, use 'alforge remove {name}' to stop tracking)")
    return 1 if failures else 0


def cmd_purge(context, args) -> int:
    failures = 0
    for name in args.names:
        try:
            target = select_target(context, name)
        except Exception:  # noqa: BLE001
            target = None
        package = _package_for(context, target, name) if target else name
        if not ui.confirm(
            f"Purge {package} and stop tracking it?", default=False
        ):
            ui.info("aborted")
            continue
        if deb.installed_version(package) is not None:
            command = deb.remove_package(package, purge=True, dry_run=context.dry_run)
            if context.dry_run:
                ui.info("would run: " + " ".join(command))
        else:
            ui.detail(f"{package} was not installed")
        if target is not None and not context.dry_run:
            context.registry.remove(target)
            context.state.drop(str(target))
            ui.ok(f"purged {package} and stopped tracking {target}")
        context.save_state()
    return 1 if failures else 0
