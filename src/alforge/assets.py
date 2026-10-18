"""Release asset selection.

GitHub/GitLab/Gitea asset names are free-form, so selection is a small scoring
problem rather than a ``grep``:

* the file must be a ``.deb``,
* the architecture must match this machine (``all``/``noarch`` is acceptable),
* debug/dev/doc/source artifacts are rejected,
* naming that resembles the repository is preferred.

When two candidates tie on the top score the caller decides: interactively the
user picks, otherwise alforge refuses to guess (``AmbiguousError``) instead of
silently installing the wrong architecture.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .deb import arch_alias_tokens, system_arch
from .errors import AmbiguousError, NotFoundError
from .providers import Asset

ALL_ARCH_TOKENS = ("all", "noarch", "any")

#: Every token that identifies *some* architecture.  Used to reject a
#: wrong-architecture build instead of falling back to it.
_KNOWN_ARCH_TOKENS: tuple[str, ...] = tuple(
    {
        token
        for arch in ("amd64", "arm64", "armhf", "i386", "riscv64", "ppc64el")
        for token in arch_alias_tokens(arch)
    }
)

ARCH_SCORE = 100
ALL_ARCH_SCORE = 40
HINT_SCORE = 15
NAME_MATCH_SCORE = 25
WRONG_ARCH_PENALTY = -1000


@dataclass
class Candidate:
    asset: Asset
    score: int
    reasons: list[str] = field(default_factory=list)

    @property
    def rejected(self) -> bool:
        return self.score < 0


def _token_present(name: str, token: str) -> bool:
    """Word-ish containment: 'amd64' matches 'app_1.0_amd64.deb', not 'damd64'."""
    pattern = rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])"
    return re.search(pattern, name, flags=re.IGNORECASE) is not None


def score_asset(
    asset: Asset,
    *,
    arch: str,
    hint: str | None = None,
    exclude: tuple[str, ...] = (),
) -> Candidate:
    name = asset.name
    lowered = name.lower()
    candidate = Candidate(asset=asset, score=0)

    if not lowered.endswith(".deb"):
        candidate.score = -10_000
        candidate.reasons.append("not a .deb")
        return candidate

    for token in exclude:
        if token and token.lower() in lowered:
            candidate.score = -10_000
            candidate.reasons.append(f"excluded token {token!r}")
            return candidate

    own_tokens = tuple(token.lower() for token in arch_alias_tokens(arch))
    if any(_token_present(lowered, token) for token in own_tokens):
        candidate.score += ARCH_SCORE
        candidate.reasons.append(f"architecture {arch}")
    elif any(_token_present(lowered, token) for token in ALL_ARCH_TOKENS):
        candidate.score += ALL_ARCH_SCORE
        candidate.reasons.append("architecture independent")
    else:
        foreign = [
            token
            for token in _KNOWN_ARCH_TOKENS
            if token.lower() not in own_tokens and _token_present(lowered, token)
        ]
        if foreign:
            candidate.score += WRONG_ARCH_PENALTY
            candidate.reasons.append(f"wrong architecture ({foreign[0]})")
        else:
            candidate.reasons.append("architecture unknown")

    if hint:
        hint_lower = hint.lower()
        if _token_present(lowered, hint_lower):
            candidate.score += HINT_SCORE
            candidate.reasons.append("name matches repository")
        stem = re.sub(r"[^a-z0-9]+", "", hint_lower)
        if stem and stem in re.sub(r"[^a-z0-9]+", "", lowered):
            candidate.score += NAME_MATCH_SCORE
            candidate.reasons.append("strong name match")

    if asset.digest:
        candidate.score += 5
        candidate.reasons.append("asset digest published")

    return candidate


def rank(
    assets: tuple[Asset, ...] | list[Asset],
    *,
    arch: str | None = None,
    hint: str | None = None,
    exclude: tuple[str, ...] = (),
) -> list[Candidate]:
    machine_arch = arch or system_arch()
    candidates = [
        score_asset(asset, arch=machine_arch, hint=hint, exclude=exclude) for asset in assets
    ]
    return sorted(candidates, key=lambda item: item.score, reverse=True)


def select(
    assets: tuple[Asset, ...] | list[Asset],
    *,
    arch: str | None = None,
    hint: str | None = None,
    exclude: tuple[str, ...] = (),
    picker=None,  # noqa: ANN001 - Callable[[list[Candidate]], Candidate | None]
) -> Candidate:
    """Pick the best .deb asset, or explain why it could not be picked."""
    ranked = rank(assets, arch=arch, hint=hint, exclude=exclude)
    usable = [candidate for candidate in ranked if not candidate.rejected]
    if not usable:
        deb_assets = [asset.name for asset in assets if asset.name.lower().endswith(".deb")]
        if not deb_assets:
            raise NotFoundError(
                "no .deb asset in this release",
                hint="the project may only publish archives or AppImages",
            )
        raise NotFoundError(
            f"no .deb asset matches architecture {arch or system_arch()}",
            hint=f"available: {', '.join(deb_assets[:5])}",
        )

    tied = [candidate for candidate in usable if candidate.score == usable[0].score]
    if len(tied) > 1:
        if picker is not None:
            chosen = picker(tied)
            if chosen is not None:
                return chosen
        raise AmbiguousError(
            "several .deb assets match equally well",
            candidates=[candidate.asset.name for candidate in tied],
            hint="name the asset explicitly or disambiguate the release",
        )
    return usable[0]
