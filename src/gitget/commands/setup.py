"""``init``, ``setup`` and ``doctor``."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from .. import __version__, deb, paths, ui
from ..config import SUPPORTED_FORGES, Registry, insecure_permissions

REGISTRY_HEADER = """\
# gitget tracking registry - one target per line.
# format: [forge:]path
#   github:owner/repo
#   gitlab:group/project
#   codeberg:owner/repo
#   gitea:git.example.org/owner/repo
#
# Learned data (debian package name, last seen version) lives in
# ~/.local/state/gitget/state.json and is never written here.
"""


def mask(token: str) -> str:
    if len(token) <= 8:
        return "*" * len(token)
    return f"{token[:4]}...{token[-4:]}"


# --------------------------------------------------------------------------- #
# init
# --------------------------------------------------------------------------- #
def cmd_init(context, args) -> int:  # noqa: ANN001
    paths.ensure_dirs()
    registry_path = paths.registry_file()
    if not registry_path.exists():
        registry_path.write_text(REGISTRY_HEADER, encoding="utf-8")
        ui.ok(f"created {registry_path}")
    else:
        ui.detail(f"registry already exists: {registry_path}")
    if not paths.config_file().exists():
        context.config.save()
        ui.ok(f"created {paths.config_file()}")
    ui.info(f"config:  {paths.config_file()}")
    ui.info(f"registry:{paths.registry_file()}")
    ui.info(f"state:   {paths.state_file()}")
    ui.info(f"log:     {paths.log_file()}")

    if getattr(args, "no_prompt", False) or not ui.is_tty():
        return 0
    if context.config.tokens:
        ui.detail("API tokens already configured, run 'gitget setup' to change them")
        return 0
    if ui.confirm("Configure a forge API token now? Highly recommended.", default=True):
        return cmd_setup(context, args)
    return 0


# --------------------------------------------------------------------------- #
# setup
# --------------------------------------------------------------------------- #
def _probe_rate_limit(context) -> None:  # noqa: ANN001
    if not context.config.token("github"):
        return
    try:
        payload = context.client.get_json("https://api.github.com/rate_limit", forge="github")
    except Exception:  # noqa: BLE001 - purely informational
        return
    core = (payload or {}).get("resources", {}).get("core", {})
    limit, remaining = core.get("limit"), core.get("remaining")
    if limit:
        ui.detail(f"github API: {remaining}/{limit} requests left this hour")


def cmd_setup(context, args) -> int:  # noqa: ANN001
    paths.ensure_dirs()

    if getattr(args, "show", False):
        if not context.config.tokens:
            ui.info("no token configured: gitget runs unauthenticated (60 requests/hour)")
            return 0
        for forge in SUPPORTED_FORGES:
            token = context.config.token(forge)
            if token:
                ui.info(f"{forge:9s} {mask(token)}")
        if insecure_permissions():
            ui.warn(f"{paths.config_file()} is readable by other users: chmod 600 it")
        _probe_rate_limit(context)
        return 0

    for forge in getattr(args, "clear", None) or []:
        if context.config.tokens.pop(forge, None):
            ui.ok(f"removed the {forge} token")
        else:
            ui.warn(f"no {forge} token was configured")

    assignments = getattr(args, "token", None) or []
    for assignment in assignments:
        forge, separator, value = assignment.partition("=")
        forge = forge.strip().lower()
        if not separator or forge not in SUPPORTED_FORGES:
            ui.error(f"expected --token FORGE=TOKEN with FORGE in {', '.join(SUPPORTED_FORGES)}")
            return 2
        if value.strip():
            context.config.tokens[forge] = value.strip()
            ui.ok(f"saved the {forge} token")
        else:
            context.config.tokens.pop(forge, None)
            ui.ok(f"cleared the {forge} token")

    if not assignments and not getattr(args, "clear", None):
        if not ui.is_tty():
            ui.error("'gitget setup' needs a terminal, or use --token FORGE=TOKEN")
            return 2
        ui.heading("Forge API tokens")
        ui.info("A token lifts GitHub's limit from 60 to 5000 requests/hour.")
        ui.info("Leave a field empty to keep the current value.")
        ui.info("Required scopes: none for public repositories ('public_repo' is enough).")
        for forge in SUPPORTED_FORGES:
            current = context.config.token(forge)
            prompt = f"{forge} token"
            if current:
                prompt += f" [{mask(current)}]"
            prompt += ": "
            value = ui.prompt_secret(prompt).strip()
            if value:
                context.config.tokens[forge] = value
                ui.ok(f"saved the {forge} token")
            elif current:
                ui.detail(f"kept the existing {forge} token")

    context.config.save()
    ui.ok(f"configuration written to {paths.config_file()} (mode 600)")
    _probe_rate_limit(context)
    return 0


# --------------------------------------------------------------------------- #
# doctor
# --------------------------------------------------------------------------- #
def _check(label: str, condition: bool, detail: str = "") -> bool:
    if condition:
        ui.ok(f"{label}{': ' + detail if detail else ''}")
    else:
        ui.warn(f"{label}{': ' + detail if detail else ''}")
    return condition


def _systemd_user_available() -> bool:
    if not shutil.which("systemctl"):
        return False
    result = subprocess.run(
        ["systemctl", "--user", "list-timers", "--no-pager"],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _linger_enabled() -> bool | None:
    if not shutil.which("loginctl"):
        return None
    result = subprocess.run(
        ["loginctl", "show-user", os.environ.get("USER", ""), "-p", "Linger"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip().endswith("yes")


def cmd_doctor(context, args) -> int:  # noqa: ANN001
    ui.heading(f"gitget {__version__} on {platform.platform()}")
    ui.heading("Environment")
    _check("python", sys.version_info >= (3, 11), platform.python_version())
    _check("dpkg", shutil.which("dpkg") is not None)
    _check("dpkg-deb", shutil.which("dpkg-deb") is not None)
    _check("apt-get", shutil.which("apt-get") is not None)
    _check("architecture", True, deb.system_arch())
    _check(
        "privileges",
        deb.sudo_usable(),
        "root" if deb.is_root() else ("passwordless sudo available" if deb.sudo_usable() else "sudo will prompt for a password"),
    )

    ui.heading("Configuration")
    _check("config file", paths.config_file().exists(), str(paths.config_file()))
    _check(
        "config permissions",
        not insecure_permissions(),
        "0600" if not insecure_permissions() else "too open, run: chmod 600 " + str(paths.config_file()),
    )
    for forge in SUPPORTED_FORGES:
        if context.config.token(forge):
            ui.ok(f"{forge} token: configured")
    if not context.config.tokens:
        ui.warn("no API token: 60 requests/hour, 'gitget setup' raises it to 5000")

    ui.heading("Tracking")
    targets = context.registry.targets
    _check("registry", paths.registry_file().exists(), str(paths.registry_file()))
    _check("tracked repositories", bool(targets), str(len(targets)))

    ui.heading("Automation")
    systemd = _check("systemd --user", _systemd_user_available())
    if systemd:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", "gitget-upgrade.timer"],
            check=False,
            capture_output=True,
            text=True,
        )
        _check("gitget-upgrade.timer", result.stdout.strip() == "active", result.stdout.strip())
        linger = _linger_enabled()
        if linger is None:
            ui.warn("cannot read the linger state, see 'loginctl enable-linger'")
        else:
            _check(
                "linger (runs while logged out)",
                linger,
                "enabled" if linger else "run: sudo loginctl enable-linger $USER",
            )
    else:
        ui.warn("systemd user session not available: automation will not work here")

    if not ui.json_mode():
        ui.info("diagnostics only, nothing was changed")
    return 0


def ensure_registry_placeholder() -> None:
    """Used by tests and by ``gitget init`` reruns."""
    registry = Registry()
    if not registry.path.exists():
        registry.path.parent.mkdir(parents=True, exist_ok=True)
        Path(registry.path).write_text(REGISTRY_HEADER, encoding="utf-8")
