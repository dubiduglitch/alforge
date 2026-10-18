"""AppImage handling: one self-contained executable, no package manager.

An AppImage is not a package, so there is nothing to hand to ``apt``.
Installing one means three things and nothing more:

* placing the file at a stable, versioned location alforge owns,
* pointing a symlink at it so the path the user launches never changes,
* registering a desktop entry and its icon so it appears in menus.

All of it is per-user and unprivileged: alforge never needs root to manage an
AppImage, which is precisely why the format is worth supporting next to ``.deb``.

Where the version comes from is the interesting part.  A ``.deb`` carries its
``Version`` field; an AppImage carries a ``X-AppImage-Version`` key in the
desktop entry its build tool embedded.  :func:`probe` reads that key, and falls
back to the release tag with a warning when the image was not built that way.
Once installed, :func:`installed_version` reads the version straight back out of
the file name -- which alforge itself chose, so it is authoritative and costs
nothing.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import paths, ui
from .errors import AlforgeError
from .versions import normalise_tag

#: Suffixes (case-insensitive) that mark a release asset as an AppImage.
APPIMAGE_SUFFIXES = (".appimage",)

#: How long the image's runtime may take to unpack the files we ask for.
EXTRACT_TIMEOUT = 90

#: Where ``--appimage-extract`` writes, relative to its working directory.
_EXTRACT_ROOT = "squashfs-root"

#: The desktop-entry key appimagetool writes the application version into.
_VERSION_KEY = "X-AppImage-Version"

#: Only a couple of sizes are ever produced; icons are placed in hicolor.
_ICON_SIZES = {".png": "256x256", ".svg": "scalable"}


@dataclass(frozen=True)
class DesktopEntry:
    """The subset of an embedded ``.desktop`` file that matters to a launcher."""

    name: str | None = None
    comment: str | None = None
    icon: str | None = None
    categories: str | None = None
    exec_line: str | None = None
    terminal: bool = False
    version: str | None = None
    update_information: str | None = None


@dataclass(frozen=True)
class AppImageInfo:
    """What :func:`probe` learned about one downloaded image."""

    name: str
    version: str
    display_name: str | None = None
    desktop: DesktopEntry | None = None
    icon: bytes | None = None
    icon_suffix: str = ".png"
    version_source: str = "embedded desktop"

    def __str__(self) -> str:
        return f"{self.name} {self.version}"


# --------------------------------------------------------------------------- #
# naming
# --------------------------------------------------------------------------- #
def is_appimage_asset(name: str) -> bool:
    return name.lower().endswith(APPIMAGE_SUFFIXES)


def slug(value: str) -> str:
    """A filesystem and command friendly name."""
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "appimage"


def app_id(target) -> str:  # noqa: ANN001 - config.Target, kept loose against cycles
    """Stable identity of an AppImage, derived from the tracked repository."""
    return slug(target.name)


def managed_dir(identifier: str) -> Path:
    return paths.appimage_dir() / identifier


def link_path(identifier: str) -> Path:
    return paths.bin_dir() / identifier


def desktop_path(identifier: str) -> Path:
    return paths.applications_dir() / f"{identifier}.desktop"


def icon_path(identifier: str, suffix: str = ".png") -> Path:
    return paths.icons_dir(_ICON_SIZES.get(suffix, "256x256")) / f"{identifier}{suffix}"


def _safe_version(version: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._+-]", "-", version.strip()).strip("-")
    return cleaned or "0"


# --------------------------------------------------------------------------- #
# reading the embedded desktop entry
# --------------------------------------------------------------------------- #
def parse_desktop(text: str) -> DesktopEntry | None:
    """Parse the ``[Desktop Entry]`` group of a ``.desktop`` file.

    ``Version=`` is deliberately ignored: in a desktop entry it is the *spec*
    version (always ``1.0``), never the application version.  Only
    ``X-AppImage-Version`` says which release of the application this is.
    """
    values: dict[str, str] = {}
    in_entry = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            in_entry = line == "[Desktop Entry]"
            continue
        if not in_entry:
            continue
        key, separator, value = line.partition("=")
        if separator:
            values.setdefault(key.strip(), value.strip())
    if not values:
        return None
    return DesktopEntry(
        name=values.get("Name") or None,
        comment=values.get("Comment") or None,
        icon=values.get("Icon") or None,
        categories=values.get("Categories") or None,
        exec_line=values.get("Exec") or None,
        terminal=values.get("Terminal", "").strip().lower() == "true",
        version=values.get(_VERSION_KEY) or None,
        update_information=values.get("X-AppImage-UpdateInformation") or None,
    )


def _desktop_from_files(files: dict[str, bytes]) -> DesktopEntry | None:
    best: DesktopEntry | None = None
    for relative in sorted(files):
        if not relative.lower().endswith(".desktop"):
            continue
        entry = parse_desktop(files[relative].decode("utf-8", errors="replace"))
        if entry is None:
            continue
        if entry.version:
            return entry
        if best is None:
            best = entry
    return best


def pick_icon(files: dict[str, bytes]) -> tuple[bytes, str] | None:
    """Largest PNG, else the largest SVG, from the extracted payload."""
    for suffix in (".png", ".svg"):
        found = [
            (name, payload)
            for name, payload in files.items()
            if name.lower().endswith(suffix)
        ]
        if found:
            _, payload = max(found, key=lambda item: len(item[1]))
            return payload, suffix
    return None


# --------------------------------------------------------------------------- #
# running the image in extract mode
# --------------------------------------------------------------------------- #
def extract(path: Path, pattern: str, *, timeout: int = EXTRACT_TIMEOUT) -> dict[str, bytes]:
    """Return the files matching *pattern* inside the image.

    ``--appimage-extract`` unpacks the squashfs payload without mounting it (so
    FUSE is not needed) and without running the application.  It does execute
    the image's own runtime, which is why callers only ever reach this after the
    checksum was verified.

    An image that refuses to unpack is not fatal: the caller falls back to the
    release tag, so a failure here returns an empty mapping rather than raising.
    """
    with tempfile.TemporaryDirectory(prefix="alforge-appimage-") as workspace:
        root = Path(workspace)
        try:
            path.chmod(path.stat().st_mode | 0o700)
            completed = subprocess.run(
                [str(path.resolve()), "--appimage-extract", pattern],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            ui.detail(f"{path.name}: cannot inspect the image ({exc})")
            return {}
        payload = root / _EXTRACT_ROOT
        if completed.returncode != 0 or not payload.is_dir():
            reason = (completed.stderr or completed.stdout or "").strip().splitlines()
            ui.detail(
                f"{path.name}: the image did not unpack"
                + (f" ({reason[-1][:160]})" if reason else "")
            )
            return {}
        files: dict[str, bytes] = {}
        for entry in sorted(payload.rglob("*")):
            if entry.is_file() and not entry.is_symlink():
                try:
                    files[str(entry.relative_to(payload))] = entry.read_bytes()
                except OSError:
                    continue
        return files


def probe(path: Path, *, app_id: str, fallback_version: str | None = None) -> AppImageInfo:
    """Learn the display name, version and icon of a downloaded image.

    The version comes from ``X-AppImage-Version``; when the image does not carry
    it the release tag is used and a warning is printed, because a version still
    has to be recorded somewhere.
    """
    files = extract(path, "*.desktop")
    desktop = _desktop_from_files(files)
    version = (desktop.version if desktop else None) or normalise_tag(fallback_version or "")
    source = "embedded desktop"
    if desktop is None or not desktop.version:
        if not version:
            raise AlforgeError(
                f"cannot determine the version of {path.name}",
                hint="the image embeds no X-AppImage-Version and the release has no tag",
            )
        source = "release tag"
        ui.warn(f"{path.name} embeds no X-AppImage-Version, using the release tag {version}")

    icon = pick_icon(files)
    if icon is None and files:
        icon = pick_icon(extract(path, "*.png")) or pick_icon(extract(path, "*.svg"))

    return AppImageInfo(
        name=app_id,
        version=version,
        display_name=desktop.name if desktop else None,
        desktop=desktop,
        icon=icon[0] if icon else None,
        icon_suffix=icon[1] if icon else ".png",
        version_source=source,
    )


# --------------------------------------------------------------------------- #
# what is installed right now
# --------------------------------------------------------------------------- #
def _version_from_name(name: str, identifier: str) -> str | None:
    prefix = identifier + "-"
    if not name.startswith(prefix) or not name.lower().endswith(APPIMAGE_SUFFIXES):
        return None
    return name[len(prefix) : -len(".AppImage")] or None


def installed_file(identifier: str) -> Path | None:
    """The image the launch link currently resolves to, if any."""
    link = link_path(identifier)
    if not link.exists():
        return None
    try:
        target = link.resolve(strict=True)
    except OSError:
        return None
    return target if target.is_file() else None


def is_installed(identifier: str) -> bool:
    return installed_file(identifier) is not None


def installed_version(identifier: str) -> str | None:
    """Version of the installed image, read from the name alforge gave it."""
    target = installed_file(identifier)
    if target is None:
        return None
    return _version_from_name(target.name, identifier)


# --------------------------------------------------------------------------- #
# installing and removing
# --------------------------------------------------------------------------- #
def install(context, target, path: Path, info: AppImageInfo) -> AppImageInfo:  # noqa: ANN001
    """Place the image, point the link at it, and register the menu entry."""
    identifier = info.name
    link = link_path(identifier)
    versioned = managed_dir(identifier) / f"{identifier}-{_safe_version(info.version)}.AppImage"

    if context.dry_run:
        ui.info(f"would install {versioned}")
        ui.info(f"would link {link}")
        ui.info(f"would create {desktop_path(identifier)}")
        return info

    if link.exists() and not link.is_symlink():
        raise AlforgeError(
            f"{link} already exists and is not managed by alforge",
            hint="rename or remove that file, then try again",
        )

    versioned.parent.mkdir(parents=True, exist_ok=True)
    partial = versioned.with_name(versioned.name + ".part")
    try:
        shutil.copyfile(path, partial)
        partial.chmod(0o755)
        os.replace(partial, versioned)
    finally:
        partial.unlink(missing_ok=True)

    _point(link, versioned)
    _write_icon(identifier, info)
    _write_desktop(identifier, info, link)
    _prune(versioned.parent, keep=versioned)
    refresh_caches()
    return info


def _point(link: Path, target: Path) -> None:
    """Replace *link* with a symlink to *target*, atomically."""
    link.parent.mkdir(parents=True, exist_ok=True)
    staged = link.with_name(link.name + ".tmp-link")
    staged.unlink(missing_ok=True)
    os.symlink(target, staged)
    os.replace(staged, link)


def _write_icon(identifier: str, info: AppImageInfo) -> None:
    if not info.icon:
        ui.detail("no icon could be extracted, the menu entry will use a generic one")
        return
    destination = icon_path(identifier, info.icon_suffix)
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")
    partial.write_bytes(info.icon)
    os.replace(partial, destination)


def _desktop_text(identifier: str, info: AppImageInfo, link: Path) -> str:
    entry = info.desktop
    name = (info.display_name or identifier).replace("\n", " ").strip() or identifier
    categories = (entry.categories if entry else None) or "Utility"
    lines = [
        "[Desktop Entry]",
        "Type=Application",
        f"Name={name}",
        f"Exec={link} %U",
        f"Icon={identifier}",
        "Terminal=false",
        f"Categories={categories}",
    ]
    if entry and entry.comment:
        lines.append(f"Comment={entry.comment.replace(chr(10), ' ').strip()}")
    lines.append("X-Alforge-Managed=true")
    return "\n".join(lines) + "\n"


def _write_desktop(identifier: str, info: AppImageInfo, link: Path) -> None:
    destination = desktop_path(identifier)
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")
    partial.write_text(_desktop_text(identifier, info, link), encoding="utf-8")
    os.replace(partial, destination)


def _prune(directory: Path, *, keep: Path) -> None:
    """Keep only the image that is live, so upgrades cannot pile up."""
    for stale in directory.glob("*.AppImage"):
        if stale != keep:
            stale.unlink(missing_ok=True)


def refresh_caches() -> None:
    """Best effort: make a new menu entry visible without a re-login."""
    commands = (
        ("update-desktop-database", str(paths.applications_dir())),
        ("gtk-update-icon-cache", "-f", "-t", str(paths.data_dir() / "icons" / "hicolor")),
    )
    for name, *arguments in commands:
        tool = shutil.which(name)
        if tool is None:
            continue
        try:
            subprocess.run([tool, *arguments], check=False, capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            continue


def remove(identifier: str, *, dry_run: bool = False) -> list[str]:
    """Delete the image, the launch link, the menu entry and the icon.

    No package manager is involved and nothing outside the user's own XDG
    directories is touched, so no password is ever requested.
    """
    link = link_path(identifier)
    directory = managed_dir(identifier)
    entry = desktop_path(identifier)
    icons = [icon_path(identifier, ".png"), icon_path(identifier, ".svg")]
    targets = [str(link), str(directory), str(entry), *(str(icon) for icon in icons)]
    if dry_run:
        return targets
    link.unlink(missing_ok=True)
    shutil.rmtree(directory, ignore_errors=True)
    entry.unlink(missing_ok=True)
    for icon in icons:
        icon.unlink(missing_ok=True)
    refresh_caches()
    return targets
