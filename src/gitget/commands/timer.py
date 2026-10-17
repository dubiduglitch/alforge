"""``gitget timer`` - wiring the set-and-forget automation.

systemd *user* units, not system ones: the registry, the tokens and the state
all live in ``$HOME``, and a root service cannot see them.  A user timer also
avoids giving a background job unrestricted root access: privilege is used only
for the single ``apt-get`` call inside ``gitget upgrade``.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from .. import deb, ui
from ..config import Config
from ..errors import GitgetError

SERVICE_NAME = "gitget-upgrade.service"
TIMER_NAME = "gitget-upgrade.timer"
DEFAULT_SCHEDULE = "daily"
DEFAULT_DELAY = "45m"


def unit_dir() -> Path:
    import os

    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "systemd" / "user"


def exec_start() -> str:
    """Absolute command that re-invokes gitget, whatever way it was installed."""
    import os

    argv0 = Path(sys.argv[0] or "gitget")
    candidate = argv0.resolve()
    if candidate.name == "gitget" and candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate)
    found = shutil.which("gitget")
    if found:
        return found
    return f"{sys.executable} -m gitget"


def render_service(command: str, *, mode: str) -> str:
    lines = [
        "[Unit]",
        "Description=gitget - keep .deb packages published on git forges up to date",
        "Documentation=man:gitget(1)",
        "After=network-online.target",
        "Wants=network-online.target",
        "",
        "[Service]",
        "Type=oneshot",
    ]
    if mode == "download":
        lines.append(f"ExecStart={command} upgrade --yes --quiet --download-only")
        notify = shutil.which("notify-send")
        if notify:
            lines.append(
                f"ExecStartPost=-{notify} -a gitget gitget "
                "'Updates downloaded - run gitget upgrade to install'"
            )
    else:
        lines.append(f"ExecStart={command} upgrade --yes --quiet")
    lines += [
        "# gitget only needs privilege for the final apt-get call.",
        "Nice=10",
        "IOSchedulingClass=idle",
        "",
        "[Install]",
        "WantedBy=default.target",
        "",
    ]
    return "\n".join(lines)


def render_timer(schedule: str, delay: str) -> str:
    return "\n".join(
        [
            "[Unit]",
            "Description=gitget automatic upgrade timer",
            "",
            "[Timer]",
            f"OnCalendar={schedule}",
            "Persistent=true",
            f"RandomizedDelaySec={delay}",
            "",
            "[Install]",
            "WantedBy=timers.target",
            "",
        ]
    )


def _systemctl(*arguments: str, check: bool = False) -> subprocess.CompletedProcess:
    if not shutil.which("systemctl"):
        raise GitgetError(
            "systemctl was not found",
            hint="this command requires a systemd user session",
        )
    result = subprocess.run(
        ["systemctl", "--user", *arguments], check=False, capture_output=True, text=True
    )
    if check and result.returncode != 0:
        raise GitgetError(
            f"systemctl --user {' '.join(arguments)} failed",
            hint=(result.stderr or result.stdout).strip() or None,
        )
    return result


def cmd_timer(context, args) -> int:  # noqa: ANN001
    action = args.action
    directory = unit_dir()
    service_path = directory / SERVICE_NAME
    timer_path = directory / TIMER_NAME
    command = exec_start()
    mode = getattr(args, "mode", None) or "install"
    schedule = getattr(args, "schedule", None) or DEFAULT_SCHEDULE
    delay = getattr(args, "randomized_delay", None) or DEFAULT_DELAY

    if action == "status":
        ui.heading("unit files")
        for path in (service_path, timer_path):
            if path.exists():
                ui.ok(str(path))
            else:
                ui.warn(f"{path} (missing)")
        ui.heading("timer")
        result = _systemctl("list-timers", TIMER_NAME, "--no-pager")
        sys.stdout.write(result.stdout)
        return 0

    if action == "remove":
        _systemctl("disable", "--now", TIMER_NAME)
        for path in (timer_path, service_path):
            if path.exists():
                path.unlink()
                ui.ok(f"removed {path}")
        _systemctl("daemon-reload")
        ui.ok("gitget automatic upgrades disabled")
        return 0

    # install
    service = render_service(command, mode=mode)
    timer = render_timer(schedule, delay)
    if context.dry_run:
        ui.heading(f"{service_path}")
        sys.stdout.write(service)
        ui.heading(f"{timer_path}")
        sys.stdout.write(timer)
        return 0

    directory.mkdir(parents=True, exist_ok=True)
    service_path.write_text(service, encoding="utf-8")
    timer_path.write_text(timer, encoding="utf-8")
    ui.ok(f"wrote {service_path}")
    ui.ok(f"wrote {timer_path}")

    _systemctl("daemon-reload", check=True)
    _systemctl("enable", "--now", TIMER_NAME, check=True)
    ui.ok(f"{TIMER_NAME} enabled ({schedule}, random delay up to {delay})")

    if mode == "install" and not deb.sudo_usable():
        ui.warn(
            "the timer runs without a terminal: apt-get will fail if sudo asks for a password"
        )
        ui.detail("options: configure passwordless sudo for apt-get, or re-run with")
        ui.detail("'gitget timer install --mode download' to only fetch packages")

    if not _linger_enabled():
        ui.warn("your user session stops at logout, so the timer will not run while logged out")
        ui.detail("enable it with: sudo loginctl enable-linger $USER")
    return 0


def _linger_enabled() -> bool:
    import os

    if not shutil.which("loginctl"):
        return True
    result = subprocess.run(
        ["loginctl", "show-user", os.environ.get("USER", ""), "-p", "Linger"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return True
    return result.stdout.strip().endswith("yes")


def config_hint(config: Config) -> str | None:
    return None if config.tokens else "no API token configured"
