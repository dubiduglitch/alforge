# gitget

Install and keep up to date `.deb` packages published on GitHub, GitLab, Codeberg and any Gitea/Forgejo instance.

- **Forge-aware**: `github:owner/repo`, `gitlab:group/project`, `codeberg:owner/repo`, `gitea:host/owner/repo`. URLs are auto-detected, short names are searched on GitHub by default.
- **Selective**: architecture-aware `.deb` scoring with exclusion filters; no accidental install of debug/arm variants on amd64.
- **Safe**: verifies SHA-256 against release manifests or asset digests; refuses to install unverified assets when `--require-checksum` is used.
- **Set-and-forget**: `gitget timer install` wires a `systemd --user` timer that runs `gitget upgrade` on a schedule (randomised delay, network-online aware).
- **Per-user, tidy**: config/registry/state under `~/.config/gitget` / `~/.local/state/gitget`. Privilege only for `apt-get install` (via `sudo`).
- **Offline-friendly**: `gitget list` reads cached state; `gitget update` is the only command that refreshes forge data.

## Install

```bash
pipx install git+https://github.com/rsxn/gitget
# or: pipx install --path /home/rsxn/Projects/gitget
```

## First run

```bash
gitget setup    # add API token (raises 60->5000 GitHub requests/hour)
gitget doctor   # sanity check
```

## Usage

```bash
gitget install obsidian                    # search + install + track
gitget install github:super-productivity/super-productivity
gitget install https://github.com/owner/repo/releases/latest

gitget list --upgradable                   # see what's due
gitget update                              # refresh, show status
gitget check                               # same as update
gitget upgrade                             # install updates
gitget remove obsidian                     # stop tracking (keep installed)
gitget purge obsidian                      # purge and stop tracking

gitget timer install                       # enable daily automatic upgrades
gitget timer status                        # check the timer
gitget timer remove                        # disable it
```

## Files

| File | Purpose |
|---|---|
| `~/.config/gitget/repos.txt` | tracked repositories (human-editable) |
| `~/.config/gitget/config.json` | API tokens (mode 0600) |
| `~/.local/state/gitget/state.json` | last-seen versions, package mapping |
| `~/.local/state/gitget/gitget.log` | audit log |

## Notes

- `gitget` never writes learned data into `repos.txt`. The Debian package name and last version are stored in `state.json`.
- For root-only contexts use `systemd --user`: the timer runs under your user and only `sudo` for `apt-get`.
- If `notify-send` is available, `gitget upgrade --notify` can desktop-notify you.
- Add `--require-checksum` to refuse to install assets without a published checksum.
- In headless/background mode, ambiguous matches are rejected (no interactive prompt).

## Exit codes

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | general failure |
| 2 | bad usage |
| 3 | network/API error |
| 4 | not found |
| 5 | ambiguous (needs explicit name) |
| 6 | checksum error |
| 7 | privilege unavailable |
| 8 | configuration problem |
