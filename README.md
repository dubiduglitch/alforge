# alforge

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![GitHub release](https://img.shields.io/github/release/dubiduglitch/alforge.svg)](https://github.com/dubiduglitch/alforge/releases/latest)

Install and keep up to date `.deb` packages published on GitHub, GitLab, Codeberg and any Gitea/Forgejo instance. One command to find, download and install the right binary for your architecture, with automatic background updates via `systemd --user`.

## Features

- **Multi-forge support** – works with GitHub, GitLab, Codeberg and self-hosted Gitea/Forgejo instances. URLs are auto-detected, short names search GitHub by default.
- **Smart asset selection** – architecture-aware scoring picks the correct `.deb` for your system, filtering out debug/dev/doc/source artifacts.
- **Automatic checksum verification** – verifies SHA-256 checksums against published manifests or asset digests, with `--require-checksum` to refuse unverified installs.
- **Set-and-forget automation** – `alforge timer install` sets up a `systemd --user` timer for automatic upgrades, with randomized delay and network-online awareness.
- **Offline-friendly** – `alforge list` reads cached state only; `update`/`upgrade` are the only network-touching commands.
- **Per-user by design** – config/registry/state under `~/.config/alforge` / `~/.local/state/alforge`. Root privileges are only used for the final `apt-get install`.

## Installation

### Using pipx (recommended)

```bash
pipx install git+https://github.com/dubiduglitch/alforge
```

### From source

```bash
git clone https://github.com/dubiduglitch/alforge.git
cd alforge
pipx install --path .
```

## First run

```bash
alforge setup    # Add API token (raises GitHub rate limit from 60 to 5000/hour)
alforge doctor   # Check environment and configuration
```

## Usage

### Install packages

```bash
alforge install obsidian                        # search + install + track
alforge install github:super-productivity/super-productivity
alforge install gitlab:fdroid/fdroidclient
alforge install https://github.com/owner/repo/releases/latest
```

### Manage tracked packages

```bash
alforge list                      # List tracked packages and their status
alforge list --upgradable         # Show packages with updates available
alforge update                    # Refresh metadata from forges
alforge check                     # Alias for 'update'
alforge upgrade                   # Install available updates
alforge add owner/repo            # Track without installing
alforge remove obsidian           # Stop tracking (keep installed)
alforge uninstall obsidian        # Remove installed package
alforge purge obsidian             # Remove package and stop tracking
```

### Automation

```bash
alforge timer install             # Enable daily automatic upgrades
alforge timer status              # Check timer status
alforge timer remove              # Disable automatic upgrades
```

## Files

| File | Purpose |
|---|---|
| `~/.config/alforge/repos.txt` | Tracked repositories (human-editable) |
| `~/.config/alforge/config.json` | API tokens (mode 0600) |
| `~/.local/state/alforge/state.json` | Last-seen versions and package mappings |
| `~/.local/state/alforge/alforge.log` | Audit log |

## Notes

- Learned data is never written to `repos.txt`; it's stored in `state.json`.
- In headless/background mode, ambiguous matches are rejected (no interactive prompts).
- If `notify-send` is available, `alforge upgrade --notify` sends a desktop notification.
- Use `--require-checksum` to refuse installing assets without a published checksum.
- For timers to run while logged out, run: `loginctl enable-linger $USER`.

## Tip jar

If `alforge` saves you time, consider leaving a small tip:

[![Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/dubiduglitch)

[![Liberapay](https://liberapay.com/assets/widgets/donate.svg)](https://liberapay.com/dubiduglitch)

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | General failure |
| 2 | Bad usage |
| 3 | Network or API error |
| 4 | Not found (repo/release/asset) |
| 5 | Ambiguous target (needs explicit name) |
| 6 | Checksum missing or mismatched |
| 7 | Privilege required but unavailable |
| 8 | Configuration problem |

## License

This project is licensed under the [MIT License](LICENSE).

## Install as a .deb

You can also install `alforge` as a native Debian package:

```bash
# Download from the latest release
wget https://github.com/dubiduglitch/alforge/releases/download/v0.1.0/alforge_0.1.0-1_all.deb
sudo dpkg -i alforge_0.1.0-1_all.deb
```

This installs `alforge` to `/usr/bin/alforge` with the Python package in `/usr/lib/python3/dist-packages/`. The package depends on `python3 (>= 3.11)`, `sudo`, `apt-utils`, and `dpkg` — all present on any Debian/Ubuntu system.

To build from source:

```bash
sudo apt install debhelper dh-python pybuild-plugin-pyproject python3-all python3-setuptools python3-wheel
dpkg-buildpackage -us -uc -b
# The .deb is written to the parent directory
```
