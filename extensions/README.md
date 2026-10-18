# alforge browser integration

A tiny content script that adds an **Install with alforge** button to GitHub,
GitLab and Codeberg project pages. Clicking it opens

```
alforge://install/<forge>/<owner>/<repo>
```

which the desktop hands to `alforge handle-uri` (registered by the `alforge.deb`
as the `x-scheme-handler/alforge`). alforge then shows the exact artifact in a
`zenity`/`kdialog` dialog and installs only after you approve.

The extension is deliberately permission-free: it reads the page it is injected
into and hands a *target* to the OS. It cannot download or install anything by
itself, and a web page cannot name an artifact — only a forge and a repository.

## Load it

Install a dialog tool first (`zenity` or `kdialog`), otherwise alforge refuses to
act on a browser request.

**Chrome / Chromium / Edge** — `chrome://extensions` → enable *Developer mode* →
*Load unpacked* → select this directory.

**Firefox** — `about:debugging#/runtime/this-firefox` → *Load Temporary Add-on* →
select `manifest.json`. (Firefox uses MV3 content scripts fine; only the
`background`/`action` parts of MV3 are limited.)

Installed from the `.deb`, the same files live in
`/usr/share/alforge/extension/chrome`.
