"""Smoke tests: init a fresh project, check it passes; break it, check it fails."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from docloom.cli import main


def _stage(root: Path) -> None:
    """The corpus is `git ls-files`-based (matching the original checker), so
    tests stage their writes before checking."""
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)


@pytest.fixture()
def project(tmp_path: Path, capsys) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    assert main(["init", "--root", str(tmp_path), "--name", "smoke"]) == 0
    _stage(tmp_path)
    capsys.readouterr()
    return tmp_path


def test_init_scaffold_passes_check(project: Path, capsys) -> None:
    _stage(project)
    assert main(["check", "--root", str(project)]) == 0
    out = capsys.readouterr().out
    assert "PASS ✓" in out


def test_untyped_doc_fails(project: Path, capsys) -> None:
    (project / "docs/rogue.md").write_text("# no frontmatter\n")
    _stage(project)
    assert main(["check", "--root", str(project)]) == 1
    assert "no frontmatter / missing type:" in capsys.readouterr().out


def test_invented_type_fails(project: Path, capsys) -> None:
    (project / "docs/rogue.md").write_text(
        "---\ntype: braindump\nstatus: active\n---\n# nope\n"
    )
    _stage(project)
    assert main(["check", "--root", str(project)]) == 1
    assert "invalid type: 'braindump'" in capsys.readouterr().out


def test_tracker_story_without_file_fails_bijection(project: Path, capsys) -> None:
    (project / "docs/sprint-status.yaml").write_text(
        "epics:\n"
        "  - epic: 1\n"
        "    title: T\n"
        "    status: in-progress\n"
        "    story_home: docs/stories/\n"
        "    stories:\n"
        "      - id: '1.1'\n"
        "        title: Ghost story\n"
        "        status: completed\n"
    )
    _stage(project)
    assert main(["check", "--root", str(project)]) == 1
    assert "tracker story 1.1: no story file" in capsys.readouterr().out


def test_completed_story_with_unresolving_anchor_fails_gate3(
    project: Path, capsys
) -> None:
    (project / "docs/stories/1-1-thing.md").write_text(
        "---\n"
        "type: story\n"
        "status: completed\n"
        "title: Thing\n"
        "anchor:\n"
        '  - symbol: "src/nowhere.py::Missing"\n'
        "---\n"
        "## Acceptance Criteria\nGiven When Then\n"
    )
    (project / "docs/sprint-status.yaml").write_text(
        "epics:\n"
        "  - epic: 1\n"
        "    title: T\n"
        "    status: in-progress\n"
        "    story_home: docs/stories/\n"
        "    stories:\n"
        "      - id: '1.1'\n"
        "        title: Thing\n"
        "        status: completed\n"
    )
    _stage(project)
    assert main(["check", "--root", str(project)]) == 1
    assert "anchor(s) don't resolve" in capsys.readouterr().out


def test_anchor_resolves_when_symbol_exists(project: Path, capsys) -> None:
    (project / "src").mkdir()
    (project / "src/thing.py").write_text("def do_thing():\n    return 1\n")
    (project / "docs/stories/1-1-thing.md").write_text(
        "---\n"
        "type: story\n"
        "status: completed\n"
        "title: Thing\n"
        "anchor:\n"
        '  - symbol: "src/thing.py::do_thing"\n'
        "---\n"
        "## Acceptance Criteria\nGiven When Then\n"
    )
    (project / "docs/sprint-status.yaml").write_text(
        "epics:\n"
        "  - epic: 1\n"
        "    title: T\n"
        "    status: in-progress\n"
        "    story_home: docs/stories/\n"
        "    stories:\n"
        "      - id: '1.1'\n"
        "        title: Thing\n"
        "        status: completed\n"
    )
    _stage(project)
    assert main(["check", "--root", str(project)]) == 0
