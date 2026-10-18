"""``add``, ``remove`` and ``list`` - managing the tracking registry."""

from __future__ import annotations

from .. import ui
from ..records import forget
from ..report import build_rows, filter_targets, render, select_target
from ..targets import resolve

__all__ = ["cmd_add", "cmd_list", "cmd_remove"]


def cmd_add(context, args) -> int:  # noqa: ANN001
    failures = 0
    for raw in args.targets:
        try:
            target = resolve(context, raw, forge=args.forge)
        except Exception as exc:  # noqa: BLE001 - reported per target, loop continues
            ui.error(f"{raw}: {exc}")
            failures += 1
            continue
        if context.registry.add(target):
            ui.ok(f"now tracking {target}")
        else:
            ui.info(f"{target} is already tracked")
    return 1 if failures else 0


def cmd_remove(context, args) -> int:
    failures = 0
    for name in args.names:
        try:
            target = select_target(context, name)
        except Exception as exc:  # noqa: BLE001
            ui.error(str(exc))
            failures += 1
            continue
        entry = context.state.get(str(target))
        if not context.dry_run and context.registry.remove(target):
            forget(context, target)
            ui.ok(f"stopped tracking {target}")
            if entry.package:
                ui.detail(
                    f"{entry.package} is still installed; "
                    f"use 'alforge uninstall {entry.package}' to remove it, "
                    f"or 'alforge purge {target.name}' for both"
                )
        else:
            ui.warn(f"{target} was not tracked")
        context.save_state()
    return 1 if failures else 0


def cmd_list(context, args) -> int:
    """Offline view: never touches the network, reads dpkg and the state file."""
    targets = filter_targets(context, getattr(args, "specs", None) or None)
    rows = build_rows(context, targets, upgradable_only=getattr(args, "upgradable", False))
    render(rows)
    return 0
