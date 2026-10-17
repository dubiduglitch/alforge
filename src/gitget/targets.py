"""Turning user input into a :class:`Target`.

Accepted forms::

    github:owner/repo            explicit forge
    gitlab:group/subgroup/proj
    codeberg:owner/repo
    gitea:git.example.org/owner/repo
    owner/repo                   default forge (github unless configured)
    https://github.com/owner/repo/releases/...
    obsidian                     free text -> forge search

Short names are only resolved interactively.  In a systemd unit there is no
terminal, so gitget fails loudly instead of picking a random repository.
"""

from __future__ import annotations

from . import ui
from .config import Target, parse_target
from .errors import AmbiguousError, NotFoundError, UsageError
from .providers import SUPPORTED, detect_url


def _interactive_picker(results):  # noqa: ANN001, ANN202
    labels = [
        f"{result.target}  ({result.stars} stars)  {result.description[:60]}"
        for result in results
    ]
    index = ui.choose("Several repositories match:", labels)
    if index is None:
        return None
    return results[index]


def resolve(
    context,  # noqa: ANN001 - Context, kept loose to avoid an import cycle
    raw: str,
    *,
    forge: str | None = None,
    picker=None,  # noqa: ANN001
) -> Target:
    """Resolve user input to a Target, searching the forge when needed."""
    value = raw.strip()
    if not value:
        raise UsageError("no repository given")

    # 1. A URL wins: it tells us both the forge and the path.
    if value.startswith(("http://", "https://")):
        detected = detect_url(value, context.client)
        if detected is None:
            raise UsageError(
                f"cannot understand {value}",
                hint="supported: github.com, gitlab.com, codeberg.org, and Gitea/Forgejo instances",
            )
        provider, path = detected
        return Target(provider.name, path)

    # 2. Explicit forge prefix, or an unqualified owner/repo.
    head, separator, _ = value.partition(":")
    if separator and head.lower() in SUPPORTED:
        return parse_target(value, default_forge=forge or "github")
    if "/" in value:
        return Target(forge or "github", value.strip("/"))

    # 3. Free text: search the forge.
    chosen_forge = forge or "github"
    provider = context.provider(chosen_forge)
    results = provider.search(value, limit=8)
    if not results:
        raise NotFoundError(
            f"no repository matching {value!r} on {chosen_forge}",
            hint="try 'gitget install owner/repo' instead",
        )
    if len(results) == 1:
        result = results[0]
        ui.detail(f"resolved to {result.target}")
        return Target(result.forge, result.path)

    if picker is None and not ui.is_tty():
        raise AmbiguousError(
            f"{len(results)} repositories match {value!r}",
            candidates=[result.target for result in results],
            hint="be explicit, for example 'gitget install owner/repo'",
        )
    pick = (picker or _interactive_picker)(results)
    if pick is None:
        raise UsageError("aborted")
    return Target(pick.forge, pick.path)
