"""Building the status table shared by ``list`` and ``update``."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from . import deb, ui
from .config import Target, short_name_matches
from .versions import is_newer

UP_TO_DATE = "up-to-date"
UPGRADABLE = "upgradable"
NOT_INSTALLED = "not-installed"
UNKNOWN = "unknown"


@dataclass
class Row:
    target: Target
    package: str
    installed: str
    latest: str
    status: str
    checked_at: str

    def as_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["target"] = str(self.target)
        return data


def _normalise(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def guess_package(target: Target, installed: dict[str, str]) -> str | None:
    """Best effort mapping from a repository name to an installed package.

    Only exact matches and *distinctive* prefixes are accepted: a short name
    such as ``r`` must never be paired with ``adduser``.
    """
    if target.name in installed:
        return target.name
    wanted = _normalise(target.name)
    if not wanted:
        return None
    for name in installed:
        if _normalise(name) == wanted:
            return name
    if len(wanted) >= 4:
        for name in installed:
            if _normalise(name).startswith(wanted):
                return name
    return None


def build_row(context, target: Target, *, installed: dict[str, str] | None = None) -> Row:  # noqa: ANN001
    entry = context.state.get(str(target))
    packages = installed if installed is not None else deb.installed_packages()
    package = entry.package or guess_package(target, packages) or ""
    current = packages.get(package) if package else None
    latest = entry.last_version

    if latest is None:
        status = UNKNOWN
    elif current is None:
        status = NOT_INSTALLED
    elif is_newer(latest, current):
        status = UPGRADABLE
    else:
        status = UP_TO_DATE

    return Row(
        target=target,
        package=package or "-",
        installed=current or "-",
        latest=latest or "-",
        status=status,
        checked_at=entry.checked_at or "-",
    )


def build_rows(context, targets: list[Target], *, upgradable_only: bool = False) -> list[Row]:  # noqa: ANN001
    installed = deb.installed_packages()
    rows = [build_row(context, target, installed=installed) for target in targets]
    if upgradable_only:
        rows = [row for row in rows if row.status in (UPGRADABLE, NOT_INSTALLED)]
    return rows


def render(rows: list[Row]) -> None:
    if ui.json_mode():
        ui.emit_json([row.as_dict() for row in rows])
        return
    if not rows:
        ui.info("no tracked repositories yet, add one with 'alforge add owner/repo'")
        return
    labels = {
        UP_TO_DATE: "up to date",
        UPGRADABLE: "upgrade available",
        NOT_INSTALLED: "not installed",
        UNKNOWN: "unknown (run alforge update)",
    }
    ui.table(
        ["TARGET", "PACKAGE", "INSTALLED", "AVAILABLE", "STATUS"],
        [
            [row.target, row.package, row.installed, row.latest, labels.get(row.status, row.status)]
            for row in rows
        ],
    )
    upgradable = sum(1 for row in rows if row.status == UPGRADABLE)
    if upgradable:
        ui.info(f"{upgradable} package(s) can be upgraded: run 'alforge upgrade'")


def select_target(context, name: str) -> Target:  # noqa: ANN001
    """Resolve a user supplied short name to exactly one tracked target."""
    from .errors import AmbiguousError, NotFoundError

    matches = context.registry.find(name)
    if not matches:
        known = ", ".join(str(target) for target in context.registry.targets) or "none"
        raise NotFoundError(
            f"{name!r} is not tracked",
            hint=f"tracked repositories: {known}",
        )
    if len(matches) > 1:
        raise AmbiguousError(
            f"{name!r} matches several tracked repositories",
            candidates=[str(target) for target in matches],
            hint="use the full '[forge:]owner/repo' form",
        )
    return matches[0]


def filter_targets(context, specs: list[str] | None) -> list[Target]:  # noqa: ANN001
    """All tracked targets, or just the ones named on the command line."""
    if not specs:
        return context.registry.targets
    selected: list[Target] = []
    for spec in specs:
        target = select_target(context, spec)
        if target not in selected:
            selected.append(target)
    return selected


__all__ = [
    "Row",
    "build_row",
    "build_rows",
    "filter_targets",
    "render",
    "select_target",
    "short_name_matches",
]
