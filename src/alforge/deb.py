"""Thin, explicit wrappers around dpkg/apt.

alforge deliberately shells out instead of reimplementing package handling.
Anything privileged goes through here so it is easy to audit.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .errors import AlforgeError, PrivilegeError

#: Debian policy: at least two characters, lowercase letters, digits, ``+``,
#: ``-`` and ``.``, starting with an alphanumeric.  Anything else is refused
#: before it can reach ``apt-get``.
PACKAGE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9+.-]+$")

ARCH_ALIASES: dict[str, tuple[str, ...]] = {
    "amd64": ("amd64", "x86_64", "x64", "linux-amd64", "linux-x64"),
    "arm64": ("arm64", "aarch64", "linux-arm64"),
    "armhf": ("armhf", "armv7", "armv7l", "linux-armv7l", "linux-armhf"),
    "i386": ("i386", "i686", "x86", "linux-386", "linux-i386"),
    "riscv64": ("riscv64",),
    "ppc64el": ("ppc64el", "ppc64le"),
}


def _run(command: list[str], *, check: bool = True, capture: bool = True) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            command, check=check, capture_output=capture, text=True
        )
    except FileNotFoundError as exc:
        raise AlforgeError(f"required command not found: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        raise AlforgeError(
            f"{' '.join(command)} failed ({exc.returncode})",
            hint=(exc.stderr or "").strip() or None,
        ) from exc


def system_arch() -> str:
    """Debian architecture of this machine."""
    if shutil.which("dpkg"):
        result = _run(["dpkg", "--print-architecture"], check=False)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    machine = platform.machine()
    fallback = {"x86_64": "amd64", "aarch64": "arm64", "armv7l": "armhf", "i686": "i386"}
    return fallback.get(machine, machine)


def arch_alias_tokens(arch: str) -> tuple[str, ...]:
    """Every spelling that means "this architecture" in an asset filename."""
    tokens = list(ARCH_ALIASES.get(arch, ()))
    if arch not in tokens:
        tokens.insert(0, arch)
    return tuple(tokens)


# --------------------------------------------------------------------------- #
# .deb inspection
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class PackageInfo:
    name: str
    version: str
    architecture: str

    def __str__(self) -> str:
        return f"{self.name} {self.version} [{self.architecture}]"


def read_control(path: Path) -> dict[str, str]:
    """Read the control file of a .deb without installing it."""
    result = _run(["dpkg-deb", "-f", str(path)], check=False)
    if result.returncode != 0:
        raise AlforgeError(f"{path} is not a readable .deb package")
    fields: dict[str, str] = {}
    current: str | None = None
    for line in result.stdout.splitlines():
        if line.startswith((" ", "\t")) and current:
            fields[current] += "\n" + line.strip()
            continue
        key, separator, value = line.partition(":")
        if not separator:
            continue
        current = key.strip()
        fields[current] = value.strip()
    return fields


def validate_package_name(name: str) -> str:
    """Refuse a package name before it can be passed to ``apt-get``/``dpkg``."""
    if not PACKAGE_NAME_RE.match(name):
        raise AlforgeError(
            f"refusing suspicious package name {name!r}",
            hint="the .deb control file does not look like a Debian package",
        )
    return name


def package_info(path: Path) -> PackageInfo:
    fields = read_control(path)
    missing = [key for key in ("Package", "Version", "Architecture") if key not in fields]
    if missing:
        raise AlforgeError(
            f"{path.name} is missing control field(s): {', '.join(missing)}",
            hint="this release asset does not look like a Debian binary package",
        )
    return PackageInfo(
        name=validate_package_name(fields["Package"]),
        version=fields["Version"],
        architecture=fields["Architecture"],
    )


def installed_version(package: str) -> str | None:
    """Installed version of a package, or None when not installed.

    Uses ``dpkg-query`` rather than parsing ``dpkg -l`` so that multiarch
    suffixes and package names containing dashes are handled correctly.
    """
    result = subprocess.run(
        ["dpkg-query", "-W", "-f=${Version}", package],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    version = result.stdout.strip()
    return version or None


def is_installed(package: str) -> bool:
    return installed_version(package) is not None


def installed_packages(*, package_pattern: str | None = None) -> dict[str, str]:
    command = ["dpkg-query", "-W", "-f=${Package} ${Version}\n"]
    if package_pattern:
        command.append(package_pattern)
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    packages: dict[str, str] = {}
    for line in result.stdout.splitlines():
        name, _, version = line.partition(" ")
        if name:
            packages[name] = version.strip()
    return packages


# --------------------------------------------------------------------------- #
# privileged operations
# --------------------------------------------------------------------------- #
def is_root() -> bool:
    return os.geteuid() == 0


def _privileged(command: list[str], *, dry_run: bool) -> list[str]:
    if is_root():
        return command
    return ["sudo"] + command


def install_local(
    path: Path,
    *,
    recommend: bool = True,
    dry_run: bool = False,
    non_interactive: bool = True,
) -> list[str]:
    """Install a local .deb with apt so dependencies are resolved in one go.

    Returns the command that was (or would have been) executed.
    """
    command = ["apt-get", "install", "-y"]
    if not recommend:
        command.append("--no-install-recommends")
    command.append(str(path.resolve()))
    full = _privileged(command, dry_run=dry_run)
    if dry_run:
        return full
    environment = dict(os.environ)
    if non_interactive:
        environment["DEBIAN_FRONTEND"] = "noninteractive"
    try:
        subprocess.run(full, check=True, env=environment)
    except subprocess.CalledProcessError as exc:
        if exc.returncode in (1, 77) and not is_root() and not _sudo_is_usable():
            raise PrivilegeError(
                "apt-get failed and sudo is not available without a password",
                hint=(
                    "run alforge interactively, or allow passwordless sudo for apt-get, "
                    "or use 'alforge upgrade --download-only' from the timer"
                ),
            ) from exc
        raise AlforgeError(f"apt-get failed with exit code {exc.returncode}") from exc
    return full


def _sudo_is_usable() -> bool:
    if is_root():
        return True
    result = subprocess.run(["sudo", "-n", "true"], check=False, capture_output=True)
    return result.returncode == 0


def sudo_usable() -> bool:
    """Public helper used by ``alforge doctor``."""
    return _sudo_is_usable()


def remove_package(package: str, *, purge: bool = False, dry_run: bool = False) -> list[str]:
    command = ["apt-get", "remove", "-y"]
    if purge:
        command.append("--purge")
    command.append(package)
    full = _privileged(command, dry_run=dry_run)
    if dry_run:
        return full
    environment = dict(os.environ)
    environment["DEBIAN_FRONTEND"] = "noninteractive"
    try:
        subprocess.run(full, check=True, env=environment)
    except subprocess.CalledProcessError as exc:
        raise AlforgeError(f"apt-get remove failed with exit code {exc.returncode}") from exc
    return full
