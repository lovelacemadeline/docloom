"""`docloom check` — the gauntlet run + report.

The output format is a deliberate byte-for-byte match of the original
crosssense checker's ``main()`` (same gates, same lines, same glyphs), so the
port can be parity-diffed against it on the same corpus.
"""

from __future__ import annotations

from pathlib import Path

from .engine import Gauntlet
from .frontmatter import parse_frontmatter


def run_check(g: Gauntlet, *, summary: bool = False, valid_if_present: bool = False) -> int:
    cfg = g.cfg
    docs = g.docs
    compliant: list[Path] = []
    noncompliant: list[tuple[Path, list[str]]] = []
    untyped = 0

    for path in docs:
        fm = parse_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
        is_untyped = fm is None or "type" not in fm
        violations = g.check_doc(path, valid_if_present)
        if violations:
            noncompliant.append((path, violations))
        else:
            if is_untyped and not valid_if_present:
                pass  # counted as noncompliant above
            elif is_untyped:
                untyped += 1  # backlog, tolerated in valid-if-present mode
            else:
                compliant.append(path)

    total = len(docs)
    typed_compliant = len(compliant)
    mode = "valid-if-present" if valid_if_present else "strict"

    # Per-doc frontmatter violations as a "path: msg" worklist.
    frontmatter_fails = [
        f"{p.relative_to(cfg.root)}: {'; '.join(v)}"
        for p, v in sorted(noncompliant, key=lambda x: str(x[0]))
    ]

    gate1 = [
        ("frontmatter typed + valid", frontmatter_fails),
        ("frontmatter is valid YAML", g.frontmatter_yaml_issues()),
        ("story Status: lines canonical", g.story_status_issues()),
        ("conventions-exempt declarations valid", g.conventions_exempt_issues()),
        ("relative links resolve", g.dangling_link_issues()),
    ]
    gate2 = [
        ("epic-number identity + home", g.epic_number_issues(docs)),
        ("story-number identity", g.story_number_issues()),
        ("tracker<->file bijection", g.bijection_issues()),
        ("tracker<->file titles agree", g.title_issues()),
        ("sprint-status canonical", g.sprint_status_issues()),
        ("registry citations resolve (ADR/C-*)", g.registry_citation_issues()),
        (
            "enactable clauses have a story (orphans)",
            g.registry_reverse_bijection_issues(),
        ),
        (
            "completed epics implement their clauses",
            g.coverage_completion_issues(),
        ),
        (
            "epic status matches its stories",
            g.epic_status_consistency_issues(),
        ),
        (
            "epic doc status matches tracker",
            g.epic_status_tracker_issues(),
        ),
    ]

    print(
        f"Doc-convention check ({mode}) — {total} tracked .md files, "
        f"{typed_compliant} typed + compliant"
    )
    if valid_if_present:
        print(f"  … untyped (retrofit backlog, tolerated in this mode): {untyped}")

    def emit_gate(num: int, name: str, checks: list[tuple[str, list[str]]]) -> int:
        n_fail = sum(len(issues) for _, issues in checks)
        print(f"\n{'✓' if not n_fail else '✗'} Gate {num} — {name}")
        for sub, issues in checks:
            if not issues:
                print(f"    ✓ {sub}")
                continue
            print(f"    ✗ {sub}: {len(issues)}")
            if not summary:
                for it in issues:
                    print(f"        - {it}")
        return n_fail

    fails = emit_gate(1, "Doc validity", gate1)
    fails += emit_gate(2, "Consistency & tracking", gate2)

    # Gate 3 — spec grounding. Advisory during rollout (anchor_enforced=false),
    # so the hard findings print but don't fail the build until the ratchet flips.
    a_hard, a_advise = g.anchor_issues()
    enforced = cfg.anchor_enforced
    tag = "" if enforced else "  [advisory — rollout]"
    counted = len(a_hard) if enforced else 0
    print(f"\n{'✓' if not counted else '✗'} Gate 3 — Spec grounding (anchors){tag}")
    if a_hard:
        mark = "✗" if enforced else "⚠"
        suffix = "" if enforced else " (would fail once enforced)"
        print(f"    {mark} anchors resolve: {len(a_hard)}{suffix}")
        if not summary:
            for it in a_hard:
                print(f"        - {it}")
    else:
        print("    ✓ anchors resolve")
    if a_advise and not summary:
        print(f"    ⚠ {len(a_advise)} advisory:")
        for it in a_advise:
            print(f"        - {it}")
    fails += counted

    # Advisory — epic source_docs resolve. Never counted into `fails`.
    sd = g.source_docs_issues()
    print(f"\n{'✓' if not sd else '⚠'} Advisory — epic source_docs resolve")
    if not sd:
        print("    ✓ all source_docs resolve")
    elif not summary:
        for it in sd:
            print(f"        - {it}")

    # Advisory — register is a citation index, not a shape/version restatement.
    rt = g.register_thinness_issues()
    print(f"\n{'✓' if not rt else '⚠'} Advisory — register is a citation index (§5.1)")
    if not rt:
        print("    ✓ register restates no shapes / enums / versions")
    else:
        print(f"    ⚠ {len(rt)} restatement(s) — register drifting from the contract:")
        if not summary:
            for it in rt:
                print(f"        - {it}")

    # Advisory — every cited clause family resolves to a register.
    uf = g.unowned_clause_family_issues()
    print(f"\n{'✓' if not uf else '⚠'} Advisory — cited clause families resolve")
    if not uf:
        print("    ✓ all cited C-*/NFR-* families resolve to a register")
    else:
        print(f"    ⚠ {len(uf)} family(ies) cited but unregistered (unchecked):")
        if not summary:
            for it in uf:
                print(f"        - {it}")

    print(f"\n{'PASS ✓' if not fails else f'FAIL ✗ — {fails} issue(s)'}")
    return 1 if fails else 0
