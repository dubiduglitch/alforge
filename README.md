# gitget

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![GitHub release](https://img.shields.io/github/release/dubiduglitch/gitget.svg)](https://github.com/dubiduglitch/gitget/releases/latest)

Install and keep up to date `.deb` packages published on GitHub, GitLab, Codeberg and any Gitea/Forgejo instance. One command to find, download and install the right binary for your architecture, with automatic background updates via `systemd --user`.

## Features

- **Multi-forge support** – works with GitHub, GitLab, Codeberg and self-hosted Gitea/Forgejo instances. URLs are auto-detected, short names search GitHub by default.
- **Smart asset selection** – architecture-aware scoring picks the correct `.deb` for your system, filtering out debug/dev/doc/source artifacts.
- **Automatic checksum verification** – verifies SHA-256 checksums against published manifests or asset digests, with `--require-checksum` to refuse unverified installs.
- **Set-and-forget automation** – `gitget timer install` sets up a `systemd --user` timer for automatic upgrades, with randomized delay and network-online awareness.
- **Offline-friendly** – `gitget list` reads cached state only; `update`/`upgrade` are the only network-touching commands.
- **Per-user by design** – config/registry/state under `~/.config/gitget` / `~/.local/state/gitget`. Root privileges are only used for the final `apt-get install`.

## Installation

### Using pipx (recommended)

```bash
pipx install git+https://github.com/dubiduglitch/gitget
```

### From source

```bash
git clone https://github.com/dubiduglitch/gitget.git
cd gitget
pipx install --path .
```

## First run

```bash
gitget setup    # Add API token (raises GitHub rate limit from 60 to 5000/hour)
gitget doctor   # Check environment and configuration
```

## Usage

### Install packages

```bash
gitget install obsidian                        # search + install + track
gitget install github:super-productivity/super-productivity
gitget install gitlab:fdroid/fdroidclient
gitget install https://github.com/owner/repo/releases/latest
```

### Manage tracked packages

```bash
gitget list                      # List tracked packages and their status
gitget list --upgradable         # Show packages with updates available
gitget update                    # Refresh metadata from forges
gitget check                     # Alias for 'update'
gitget upgrade                   # Install available updates
gitget add owner/repo            # Track without installing
gitget remove obsidian           # Stop tracking (keep installed)
gitget uninstall obsidian        # Remove installed package
gitget purge obsidian             # Remove package and stop tracking
```

### Automation

```bash
gitget timer install             # Enable daily automatic upgrades
gitget timer status              # Check timer status
gitget timer remove              # Disable automatic upgrades
```

## Files

| File | Purpose |
|---|---|
| `~/.config/gitget/repos.txt` | Tracked repositories (human-editable) |
| `~/.config/gitget/config.json` | API tokens (mode 0600) |
| `~/.local/state/gitget/state.json` | Last-seen versions and package mappings |
| `~/.local/state/gitget/gitget.log` | Audit log |

## Notes

- Learned data is never written to `repos.txt`; it's stored in `state.json`.
- In headless/background mode, ambiguous matches are rejected (no interactive prompts).
- If `notify-send` is available, `gitget upgrade --notify` sends a desktop notification.
- Use `--require-checksum` to refuse installing assets without a published checksum.
- For timers to run while logged out, run: `loginctl enable-linger $USER`.

## Tip jar

If `gitget` saves you time, consider leaving a small tip:

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

You can also install `gitget` as a native Debian package:

```bash
# Download from the latest release
wget https://github.com/dubiduglitch/gitget/releases/download/v0.1.0/gitget_0.1.0-1_all.deb
sudo dpkg -i gitget_0.1.0-1_all.deb
```

This installs `gitget` to `/usr/bin/gitget` with the Python package in `/usr/lib/python3/dist-packages/`. The package depends on `python3 (>= 3.11)`, `sudo`, `apt-utils`, and `dpkg` — all present on any Debian/Ubuntu system.

To build from source:

```bash
sudo apt install debhelper dh-python pybuild-plugin-pyproject python3-all python3-setuptools python3-wheel
dpkg-buildpackage -us -uc -b
# The .deb is written to the parent directory
```
