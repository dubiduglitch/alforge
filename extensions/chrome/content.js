/*
 * Add an "Install with alforge" button to a forge project page.
 *
 * A click opens alforge://install/<forge>/<owner>/<repo>.  The desktop hands
 * that URI to `alforge handle-uri`, which shows the exact artifact and asks for
 * confirmation before anything is downloaded or installed.
 *
 * The extension is intentionally tiny and permission-free: it only reads the
 * page it is injected into and hands a *target* to the OS.  It cannot install
 * anything on its own.
 */

const SITES = [
  { host: "github.com", forge: "github" },
  { host: "gitlab.com", forge: "gitlab" },
  { host: "codeberg.org", forge: "codeberg" },
];

/* First path segments that are a site area, never an account name. */
const RESERVED = new Set([
  "about", "account", "apps", "codespaces", "collections", "dashboard",
  "discussions", "enterprise", "events", "explore", "features", "help",
  "issues", "login", "logout", "marketplace", "new", "notifications",
  "organizations", "orgs", "pricing", "pulls", "search", "security",
  "sessions", "settings", "signup", "site", "sponsors", "stars", "team",
  "topics", "trending", "users", "watching", "groups", "projects",
]);

const BUTTON_ID = "alforge-install-button";

function projectFromPath(forge, pathname) {
  const parts = pathname.split("/").filter(Boolean);
  if (parts.length < 2) return null;
  if (RESERVED.has(parts[0].toLowerCase())) return null;
  // GitLab nests projects under groups (group/subgroup/project).  We cannot tell
  // a subgroup from a project without an API call, so subgroups are not
  // supported here: the first two segments are used as-is.
  return { forge, owner: parts[0], repo: parts[1].replace(/\.git$/, "") };
}

function githubProjectFromMeta() {
  const meta = document.querySelector('meta[name="octolytics-dimension-repository_nwo"]');
  if (!meta || !meta.content || !meta.content.includes("/")) return null;
  const [owner, repo] = meta.content.split("/");
  if (!owner || !repo) return null;
  return { forge: "github", owner, repo };
}

function currentProject() {
  const site = SITES.find((candidate) => candidate.host === location.hostname);
  if (!site) return null;
  if (site.forge === "github") {
    const fromMeta = githubProjectFromMeta();
    if (fromMeta) return fromMeta;
  }
  return projectFromPath(site.forge, location.pathname);
}

function installUri({ forge, owner, repo }) {
  return `alforge://install/${forge}/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}`;
}

function mount() {
  const project = currentProject();
  const existing = document.getElementById(BUTTON_ID);

  if (!project) {
    if (existing) existing.remove();
    return;
  }

  const href = installUri(project);
  if (existing) {
    existing.href = href;
    return;
  }

  const link = document.createElement("a");
  link.id = BUTTON_ID;
  link.className = "alforge-install-button";
  link.href = href;
  link.textContent = "Install with alforge";
  link.title = `Install ${project.owner}/${project.repo} with alforge`;
  document.body.appendChild(link);
}

mount();

// These forges navigate in place, so re-check the URL once a second instead of
// depending on their internal routing events.
let lastUrl = location.href;
setInterval(() => {
  if (location.href !== lastUrl) {
    lastUrl = location.href;
    mount();
  }
}, 1000);
