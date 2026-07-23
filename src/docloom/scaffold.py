"""`docloom init` — bootstrap the doc system into a (possibly existing) project.

Idempotent and non-destructive: never overwrites an existing file; appends
clearly-delimited sections to CLAUDE.md; prints the pre-commit snippet instead
of mangling an existing .pre-commit-config.yaml.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

DOC_DIRS = (
    "docs/product",
    "docs/epics",
    "docs/stories",
    "docs/adr",
    "docs/reference",
    "docs/runbooks",
    "docs/research",
    "docs/status",
)


def _template(name: str) -> str:
    return (resources.files("docloom") / "templates" / name).read_text(
        encoding="utf-8"
    )


def _write_new(path: Path, content: str, made: list[str], skipped: list[str]) -> None:
    if path.exists():
        skipped.append(str(path))
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    made.append(str(path))


def init_project(
    root: Path, *, name: str | None, advisory: bool, claude: bool
) -> int:
    name = name or root.name
    made: list[str] = []
    skipped: list[str] = []

    for d in DOC_DIRS:
        (root / d).mkdir(parents=True, exist_ok=True)

    subs = {
        "{{PROJECT}}": name,
        "{{GATE3_ENFORCED}}": "false" if advisory else "true",
    }

    def render(template: str) -> str:
        text = _template(template)
        for k, v in subs.items():
            text = text.replace(k, v)
        return text

    _write_new(root / "docloom.toml", render("docloom.toml"), made, skipped)
    _write_new(
        root / "docs/doc-conventions.md", render("doc-conventions.md"), made, skipped
    )
    _write_new(
        root / "docs/sprint-status.yaml", render("sprint-status.yaml"), made, skipped
    )
    _write_new(root / "docs/epics/index.md", render("epics-index.md"), made, skipped)
    _write_new(root / "docs/adr/index.md", render("adr-index.md"), made, skipped)

    if claude:
        _write_new(
            root / ".claude/skills/docloom/SKILL.md",
            render("SKILL.md"),
            made,
            skipped,
        )
        claude_md = root / "CLAUDE.md"
        section = render("claude-section.md")
        marker = "## Documentation — docloom"
        if not claude_md.exists():
            claude_md.write_text(
                "---\ntype: guide\nstatus: active\n"
                f"title: Claude Code Project Instructions — {name}\n---\n\n"
                f"# Claude Code Project Instructions\n\n{section}",
                encoding="utf-8",
            )
            made.append(str(claude_md))
        elif marker not in claude_md.read_text(encoding="utf-8"):
            with claude_md.open("a", encoding="utf-8") as fh:
                fh.write(f"\n{section}")
            made.append(f"{claude_md} (section appended)")
        else:
            skipped.append(f"{claude_md} (section already present)")

    pre_commit = root / ".pre-commit-config.yaml"
    if not pre_commit.exists():
        _write_new(pre_commit, render("pre-commit-config.yaml"), made, skipped)
    else:
        skipped.append(str(pre_commit))
        print(
            "NOTE: .pre-commit-config.yaml already exists — add this hook yourself:\n"
        )
        print(render("pre-commit-config.yaml"))

    print(f"docloom init — {name}")
    for p in made:
        print(f"  + {p}")
    for p in skipped:
        print(f"  = kept existing: {p}")
    print(
        "\nNext steps:\n"
        "  1. read docs/doc-conventions.md (the convention your docs now follow)\n"
        "  2. `docloom check` — should PASS on the fresh scaffold\n"
        "  3. `pre-commit install` if you use pre-commit\n"
        "  4. in a Claude Code session: 'use the docloom skill to record what "
        "we've built'"
    )
    return 0
