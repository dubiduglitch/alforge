# Exit Codes

| Code | Meaning |
|---|---|
| 0 | Success. Command completed without error. |
| 1 | General failure. Check the error message and `~/.local/state/alforge/alforge.log`. |
| 2 | Bad usage. Invalid command line arguments or missing target. |
| 3 | Network or API failure. Cannot reach the forge, or it answered unexpectedly. |
| 4 | Not found. Repository, release or asset could not be found. |
| 5 | Ambiguous target. Several matches and no interactive terminal to ask. Use an explicit `[forge:]owner/repo`. |
| 6 | Checksum error. Downloaded artifact does not match the published checksum, or no checksum is published and `--require-checksum` is in effect. |
| 7 | Privilege error. A privileged operation is required but `sudo` is not usable in this context. |
| 8 | Configuration error. `config.json` or `repos.txt` is malformed or unreadable. |
