"""Engine regression tests — ported from the original checker's unit suite
(the corpus-gate half stayed behind: enforcing a live repo's docs is
`docloom check`'s job, not the package's test suite's).

These pin the engine behaviors most likely to break under refactor: the
frontmatter parser's unterminated-block guard, data-driven register discovery,
the register engine's extensibility (a brand-new register is checked with zero
code edits), advisory consistency, and the exemption escape hatch validating
itself. Fixture-driven throughout — no git repo needed (the corpus walk falls
back to rglob), no live corpus assumed.
"""

from __future__ import annotations

import re
from pathlib import Path

from docloom.config import Config
from docloom.engine import Gauntlet, RegisterSpec, _prefix_re
from docloom.frontmatter import parse_frontmatter


def _gauntlet(root: Path) -> Gauntlet:
    return Gauntlet(Config(root=root))


def test_frontmatter_unterminated_block_guard() -> None:
    """A frontmatter block with no closing `---` must NOT read as typed just
    because a body `---` rule appears later (parser regression guard)."""
    assert parse_frontmatter("---\ntype: story\nstatus: completed\n---\nok\n")
    assert parse_frontmatter("---\ntype: story\n# Heading\n\n---\nbody\n") is None


SYNTHETIC_REGISTER = (
    "---\n"
    "type: register\n"
    "status: active\n"
    "title: Synthetic register\n"
    "register:\n"
    "  name: synthetic-test\n"
    "  clause-prefixes: [C-TEST]\n"
    "  crosscutting-prefixes: [NFR-TEST]\n"
    '  enactable-glyphs: ["🔴", "🟡", "🟢"]\n'
    "  owner-map:\n"
    "    heading: '### FR Coverage Map'\n"
    "    until: '## Register notes'\n"
    "    line: '- \\*\\*Epic (\\d+):\\*\\*'\n"
    "---\n\n"
    "## Clauses\n"
    "- **C-TEST-1** 🔴 — a greenfield clause nobody cites (should orphan)\n"
    "- **C-TEST-2** ⬜ — an FE-dep clause (non-enactable, must NOT orphan)\n\n"
    "### FR Coverage Map\n"
    "- **Epic 99:** C-TEST-1, C-TEST-2\n\n"
    "## Register notes\n"
)


def test_register_discovery_is_data_driven(tmp_path: Path) -> None:
    """A register is discovered purely from its `register:` block — fields,
    glyph legend, and owner-map all come from the doc, nothing from code."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/synthetic-register.md").write_text(
        SYNTHETIC_REGISTER, encoding="utf-8"
    )
    g = _gauntlet(tmp_path)
    specs = {s.name: s for s in g._register_specs}
    assert "synthetic-test" in specs
    spec = specs["synthetic-test"]
    assert spec.clause_prefixes == ("C-TEST",)
    assert spec.crosscut_prefixes == ("NFR-TEST",)
    assert set(spec.enactable_glyphs) == {"🔴", "🟡", "🟢"}
    assert spec.owner_line is not None  # owner-map declared -> coverage enabled
    # Discovery is non-vacuous: the register actually defines clauses + owners.
    assert g._defined_ids(spec) == frozenset({"C-TEST-1", "C-TEST-2"})
    assert g._clause_ownership(spec) == {"C-TEST-1": 99, "C-TEST-2": 99}


def test_register_engine_is_extensible(tmp_path: Path) -> None:
    """The SAME check code fires on a brand-new register with no engine edit:
    the enactable (🔴) uncited clause orphans; the FE-dep (⬜) one does not."""
    reg = tmp_path / "synthetic-register.md"
    reg.write_text(SYNTHETIC_REGISTER, encoding="utf-8")
    spec = RegisterSpec(
        name="synthetic-test",
        path=reg,
        clause_prefixes=("C-TEST",),
        crosscut_prefixes=(),
        clause_re=_prefix_re(["C-TEST"]),
        crosscut_re=None,
        enactable_glyphs=("🔴", "🟡", "🟢"),
        proposed=frozenset(),
        owner_heading="### FR Coverage Map",
        owner_until="## Register notes",
        owner_line=re.compile(r"- \*\*Epic (\d+):\*\*"),
    )
    g = _gauntlet(tmp_path)
    glyphs = g._clause_glyphs(spec)
    assert "🔴" in glyphs["C-TEST-1"] and "⬜" in glyphs["C-TEST-2"]
    orphans = g.registry_reverse_bijection_issues(specs=(spec,))
    assert any("C-TEST-1" in o for o in orphans), "enactable clause not orphaned"
    assert not any("C-TEST-2" in o for o in orphans), "FE-dep wrongly orphaned"


def test_register_block_never_reads_as_content(tmp_path: Path) -> None:
    """The `register:` frontmatter block's own prefix declarations must not
    count as clause *definitions* — only BODY occurrences define ids."""
    reg = tmp_path / "empty-register.md"
    reg.write_text(
        "---\ntype: register\nstatus: active\ntitle: Empty\n"
        "register:\n  name: empty\n  clause-prefixes: [C-EMPTY]\n"
        "  proposed: [C-EMPTY-9]\n---\n\n# No clauses defined in the body.\n",
        encoding="utf-8",
    )
    g = _gauntlet(tmp_path)
    (spec,) = g._register_specs
    assert g._defined_ids(spec) == frozenset()


def test_unowned_family_advisory_is_consistent(tmp_path: Path) -> None:
    """The unowned-family advisory NEVER flags a family a register owns; it
    surfaces genuinely unregistered families (the old silent blind spot)."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/synthetic-register.md").write_text(
        SYNTHETIC_REGISTER, encoding="utf-8"
    )
    (tmp_path / "docs/citer.md").write_text(
        "---\ntype: reference\nstatus: active\ntitle: Citer\n---\n"
        "Cites C-TEST-1 (owned) and C-ROGUE-7 (nobody owns C-ROGUE).\n",
        encoding="utf-8",
    )
    g = _gauntlet(tmp_path)
    issues = g.unowned_clause_family_issues()
    assert any(line.startswith("C-ROGUE:") for line in issues)
    assert not any(line.startswith("C-TEST:") for line in issues)


def test_conventions_exempt_self_validates(tmp_path: Path) -> None:
    """The exemption escape hatch is held to the standard it grants: a
    declaration must be a {check: reason} map over the closed check set with
    non-empty reasons — it can't itself become an ungoverned back door."""
    g = _gauntlet(tmp_path)
    assert g._validate_exempt(None, "x") == []  # absent is fine
    assert g._validate_exempt({"title": "a real reason"}, "x") == []  # well-formed
    assert g._validate_exempt(["title"], "x")  # not a map -> rejected
    assert any("unknown check" in m for m in g._validate_exempt({"nope": "r"}, "x"))
    assert any("reason" in m for m in g._validate_exempt({"title": ""}, "x"))
    assert any("reason" in m for m in g._validate_exempt({"title": None}, "x"))
