"""Git-backed corpus discovery + change signals, degrading safe without git."""

from __future__ import annotations

import subprocess
from pathlib import Path


def tracked_markdown(root: Path, exclude_prefixes: tuple[str, ...]) -> list[Path]:
    """Every tracked .md under root (git ls-files), minus excluded prefixes.
    Falls back to a filesystem walk when the root isn't a git repo, so the
    gauntlet still runs on a not-yet-committed scratch project."""
    try:
        out = subprocess.run(
            ["git", "ls-files", "*.md"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()
        rels = out
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        rels = sorted(
            str(p.relative_to(root))
            for p in root.rglob("*.md")
            if ".git/" not in str(p.relative_to(root)) + "/"
        )
    return [root / p for p in rels if not p.startswith(exclude_prefixes)]


def last_commit_date(root: Path, rel: str) -> str:
    """Last-commit date (YYYY-MM-DD) for a path, or 'uncommitted' if none.

    Used to annotate a collision so the reviewer can see which of the two docs
    is the likely accidental newcomer.
    """
    try:
        out = subprocess.run(
            ["git", "log", "-1", "--format=%cs", "--", rel],
            cwd=root,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (FileNotFoundError, OSError):
        out = ""
    return out or "uncommitted"


def touched_files(root: Path, base_branch: str) -> frozenset[str]:
    """Files changed on this branch vs merge-base with the base branch (empty if
    git or the base ref is unavailable — the 'begun in-branch' nudge degrades
    safe rather than false-firing)."""
    try:
        mb = subprocess.run(
            ["git", "merge-base", "HEAD", base_branch],
            cwd=root,
            capture_output=True,
            text=True,
        )
        if mb.returncode != 0:
            return frozenset()
        diff = subprocess.run(
            ["git", "diff", "--name-only", f"{mb.stdout.strip()}..HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
        )
        return frozenset(diff.stdout.split())
    except (FileNotFoundError, OSError):
        return frozenset()
