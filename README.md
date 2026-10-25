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
alforge purge obsidian            # Remove package and stop tracking
```

### Automation

```bash
alforge timer install             # Enable daily automatic upgrades
alforge timer install --mode download   # Only fetch, never needs sudo
alforge timer status              # Check timer status
alforge timer remove              # Disable automatic upgrades
```

### Pre-releases and staged downloads

```bash
alforge upgrade --download-only   # Fetch and verify now, install later
alforge install obsidian --allow-prerelease   # Opt into betas
```

`alforge` follows the newest **stable** release. When a project's latest release
is flagged as a pre-release, alforge falls back to the newest stable one (pass
`--allow-prerelease` to install the beta instead).

`--download-only` never calls `sudo`: it fetches and verifies the artifact into
`~/.cache/alforge/downloads` and records the version it saw, so `alforge list`
shows what is available. Because the cache key is derived from the asset id, an
unchanged release is reused on the next run instead of being downloaded again.

### Install from the browser

The `.deb` registers the `alforge://` URI scheme, so a web page can ask alforge to
install a project — the same trick GNOME-Look uses:

```bash
alforge://install/github/owner/repo      # install and start tracking
alforge://track/codeberg/owner/repo      # only start tracking
```

A small content script adds an **Install with alforge** button to GitHub, GitLab
and Codeberg project pages; clicking it just opens the matching URI. alforge then
fetches the release, shows the **exact** artifact in a `zenity`/`kdialog` dialog,
and installs only after you approve.

Only forge *targets* are accepted: the scheme refuses a direct `.deb` URL, a
query, a fragment, or an unknown forge, so a random web page can never point the
pipeline at an artifact of its choosing. A missing dialog tool refuses too —
approval is never assumed.

A page can start alforge, so the run is never silent: a failure (no `.deb`
published, unknown repository, bad URI) raises an error box, and a success or an
up-to-date check shows a short pop-up.

Load the extension (a copy ships at `/usr/share/alforge/extension/chrome`):

1. Install `zenity` or `kdialog` for the confirmation dialog.
2. Open `chrome://extensions`, enable *Developer mode*, click *Load unpacked*, and
   pick that directory.
3. Visit any project page and click the button.

Firefox can load the same unpacked directory from `about:debugging`.

## Files

| File | Purpose |
|---|---|
| `~/.config/alforge/repos.txt` | Tracked repositories (human-editable) |
| `~/.config/alforge/config.json` | API tokens (mode 0600) |
| `~/.local/state/alforge/state.json` | Last-seen versions and package mappings |
| `~/.local/state/alforge/alforge.log` | Audit log |
| `~/.cache/alforge/downloads/` | Verified artifacts awaiting install |

## Notes

- Learned data is never written to `repos.txt`; it's stored in `state.json`.
- In headless/background mode, ambiguous matches are rejected (no interactive prompts).
- Only one alforge run writes at a time: a timer run that finds a manual upgrade
  in progress skips instead of queuing up behind it.
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
wget https://github.com/dubiduglitch/alforge/releases/download/v0.3.1/alforge_0.3.1-1_all.deb
sudo dpkg -i alforge_0.3.1-1_all.deb
```

This installs `alforge` to `/usr/bin/alforge` with the Python package in `/usr/lib/python3/dist-packages/`. The package depends on `python3 (>= 3.11)`, `sudo`, `apt-utils`, and `dpkg` — all present on any Debian/Ubuntu system.

To build from source:

```bash
sudo apt install debhelper dh-python pybuild-plugin-pyproject python3-all python3-setuptools python3-wheel
dpkg-buildpackage -us -uc -b
# The .deb is written to the parent directory
```
