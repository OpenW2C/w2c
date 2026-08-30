"""Interactive / validated git_delivery resolution for init and migrate."""
from __future__ import annotations

import sys
from pathlib import Path

from w2c import local as w2c_local
from w2c.local import (
    GIT_DELIVERY_MILESTONE,
    GIT_DELIVERY_SLICE,
    GitDeliveryError,
    load_repo_config,
    normalize_git_delivery,
)


def prompt_git_delivery() -> str:
    """Interactive mandatory choice for git_delivery. Raises GitDeliveryError if skipped."""
    print("Choose git_delivery (required — cannot skip):")
    print(
        f"  1) {GIT_DELIVERY_SLICE}  [recommended]"
        " — local commit ask after each slice; push ask then PR ask after milestone"
    )
    print(
        f"  2) {GIT_DELIVERY_MILESTONE}"
        " — local commit ask after milestone; then push ask; then PR ask"
    )
    try:
        raw = input("Enter 1 or 2: ").strip()
    except EOFError as e:
        raise GitDeliveryError(
            "git_delivery is required; pass --git-delivery "
            f"{GIT_DELIVERY_SLICE}|{GIT_DELIVERY_MILESTONE}"
        ) from e
    if raw == "1":
        return GIT_DELIVERY_SLICE
    if raw == "2":
        return GIT_DELIVERY_MILESTONE
    raise GitDeliveryError(
        "git_delivery is required; choose 1 or 2, or pass --git-delivery "
        f"{GIT_DELIVERY_SLICE}|{GIT_DELIVERY_MILESTONE}"
    )


def resolve_git_delivery(
    root: Path,
    git_delivery: str | None,
    *,
    allow_prompt: bool = True,
) -> str:
    """Return a valid git_delivery, prompting or erroring when unset."""
    if git_delivery is not None:
        normalized = normalize_git_delivery(git_delivery)
        if normalized is None:
            raise GitDeliveryError(
                "invalid --git-delivery; expected "
                f"{GIT_DELIVERY_SLICE} or {GIT_DELIVERY_MILESTONE}"
            )
        return normalized
    existing = load_repo_config(root).get("git_delivery")
    if existing:
        return str(existing)
    if allow_prompt and sys.stdin.isatty():
        return prompt_git_delivery()
    raise GitDeliveryError(
        "git_delivery is required; pass --git-delivery "
        f"{GIT_DELIVERY_SLICE}|{GIT_DELIVERY_MILESTONE}"
        " (or re-run in a TTY to choose interactively)"
    )


