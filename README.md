# gitget

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/gitget.svg)](https://pypi.org/project/gitget/)
[![GitHub release](https://img.shields.io/github/release/dubiduglitch/gitget.svg)](https://github.com/dubiduglitch/gitget/releases/latest)

Install and keep up to date `.deb` packages published on GitHub, GitLab, Codeberg and any Gitea/Forgejo instance. One command to find, download and install the right binary for your architecture, with automatic background updates via `systemd --user`.

## Features

- **Multi-forge support** – works with GitHub, GitLab, Codeberg and self-hosted Gitea/Forgejo instances. URLs are auto-detected, short names search GitHub by default.
- **Smart asset selection** – architecture-aware scoring picks the correct `.deb` for your system (amd64/arm64/etc.), filtering out debug/dev/doc/source artifacts.
- **Automatic checksum verification** – verifies SHA-256 checksums against published manifests or asset digests, with `--require-checksum` to refuse unverified installs.
- **Set-and-forget automation** – `gitget timer install` sets up a `systemd --user` timer to upgrade tracked packages on a schedule, with randomized delay and network-online awareness.
- **Offline-friendly** – `gitget list` reads cached state only. Only `update`/`upgrade` hit the network.
- **Per-user by design** – config, registry and state live under `~/.config/gitget` and `~/.local/state/gitget`. Root privileges are only used for the final `apt-get install`.

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
gitget setup    # Add API token (raises 60->5000 GitHub requests/hour)
gitget doctor   # Check environment and configuration
```

## Usage

### Install packages

```bash
# Search and install, track automatically
gitget install obsidian

# Install using explicit forge and repo
gitget install github:super-productivity/super-productivity
gitget install gitlab:fdroid/fdroidclient

# Install directly from a release URL
gitget install https://github.com/owner/repo/releases/latest
```

### Manage tracked packages

```bash
gitget list                      # List all tracked packages and their status
gitget list --upgradable         # Show packages with updates available
gitget update                    # Refresh metadata from forges (like apt update)
gitget check                     # Alias for 'update'
gitget upgrade                   # Install available updates
gitget add owner/repo            # Track a repository without installing
gitget remove obsidian           # Stop tracking (keep package installed)
gitget uninstall obsidian        # Remove the installed package
gitget purge obsidian             # Remove package and stop tracking it
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

- `gitget` never writes learned data into `repos.txt`. The Debian package name and last seen version are stored in `state.json`.
- When running unattended (systemd timers), ambiguous matches are rejected instead of prompting.
- If `notify-send` is available, `gitget upgrade --notify` will send a desktop notification.
- Use `--require-checksum` to refuse installing assets with no published checksum.
- `systemd --user` timers run under your user session. If you want them to run while logged out, enable linger with `loginctl enable-linger $USER`.

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

## Tip jar

If `gitget` saved you time or keeps your GitHub-downloaded `.deb` packages up to date, you can tip the project:

- [GitHub Sponsors](https://github.com/sponsors/dubiduglitch)
- [Buy Me a Coffee](https://buymeacoffee.com/dubiduglitch)
- [Ko-fi](https://ko-fi.com/dubiduglitch)
- [Liberapay](https://liberapay.com/dubiduglitch)
