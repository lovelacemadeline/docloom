"""`docloom context <epic-or-story>` — emit a tiered path manifest of every doc
related to a "thing to be done", so a fresh (agent) session can pull all
relevant context before starting work.

Deterministic: emits PATHS (plus register row ids) only; the reader reads them.
It walks the same doc graph the gauntlet enforces — epic doc, story files, each
discovered clause register's ownership/citations, cited ADRs, and the epic's
`source_docs:` — so the manifest can never drift from the enforced formats.

Ported from the crosssense-docs-context command, generalized: Tier 3 iterates
every discovered register (not one hardcoded path), and repo-specific extras
(the contracts freshness banner) stayed behind.
"""

from __future__ import annotations

import re
from pathlib import Path

from .engine import _ADR_CITE, Gauntlet
from .frontmatter import parse_frontmatter, parse_frontmatter_full


def resolve_target(arg: str) -> tuple[int, str | None]:
    """(epic_number, story_id_or_None). Accepts 25 / epic-25 / 26.1 / 26-1."""
    s = arg.strip().lower()
    s = s[len("epic-") :] if s.startswith("epic-") else s
    s = s[len("story-") :] if s.startswith("story-") else s
    m = re.match(r"^(\d+)[.\-]([0-9]+[a-z]?)$", s)  # story: N.M / N-M
    if m:
        return int(m.group(1)), f"{m.group(1)}.{m.group(2)}"
    m = re.match(r"^(\d+)$", s)  # epic
    if m:
        return int(m.group(1)), None
    raise SystemExit(
        f"docloom: unrecognised target {arg!r} — expected e.g. 26, epic-26, 26.1"
    )


def run_context(g: Gauntlet, target: str) -> int:
    root = g.root
    epic_num, story_id = resolve_target(target)
    scope = f"Story {story_id}" if story_id else f"Epic {epic_num}"

    def rel(p: Path) -> str:
        try:
            return str(p.relative_to(root))
        except ValueError:
            return str(p)

    epic_doc = g._epic_doc(epic_num)
    if story_id:
        story_files = g._story_files_for_id(story_id)
    else:
        story_files = g._story_files_for_epic(epic_num)

    # Text corpus to scrape citations from: epic doc + the in-scope story files.
    corpus = ""
    for p in [epic_doc, *story_files]:
        if p.exists():
            corpus += "\n" + p.read_text(encoding="utf-8", errors="replace")

    out: list[str] = [f"CONTEXT MANIFEST — {scope}", ""]

    out.append("TIER 1  the epic")
    out.append(f"  {rel(epic_doc)}" + ("" if epic_doc.exists() else "   (MISSING)"))
    out.append("")

    out.append(f"TIER 2  its stories ({len(story_files)})")
    for p in story_files:
        out.append(f"  {rel(p)}")
    if not story_files:
        home = next(
            (
                e.get("story_home")
                for e in g._tracker_epics
                if e.get("epic") == epic_num
            ),
            None,
        )
        if home == "inline":
            ids = g._inline_story_ids(epic_doc)
            wanted = [story_id] if story_id else ids
            out.append(
                f"  (inline in the epic doc — `## Story N.M` sections: "
                f"{', '.join(i for i in ids if i in wanted) or 'none'})"
            )
        else:
            out.append(f"  (none found under {g.cfg.stories_dir}/)")
    out.append("")

    # Tier 3 — every discovered clause register: rows this epic owns (inverted
    # owner-map) plus, for a story, rows its corpus cites.
    out.append("TIER 3  owned / cited register clauses (the citeable spine)")
    any_rows = False
    for spec in g._register_specs:
        owned = {c for c, e in g._clause_ownership(spec).items() if e == epic_num}
        cited = set(spec.clause_re.findall(corpus)) if story_id else set()
        rows = sorted(owned | cited)
        if rows:
            any_rows = True
            out.append(f"  {rel(spec.path)}")
            out.append(f"    → rows: {', '.join(rows)}")
    if not any_rows:
        out.append("  (no register clauses owned or cited)")
    out.append("")

    out.append("TIER 4  related ADRs (decisions)")
    adr_nums = sorted({int(n) for n in _ADR_CITE.findall(corpus)})
    for n in adr_nums:
        matches = sorted(g.cfg.adr_path.glob(f"{n:04d}-*.md"))
        if not matches:
            out.append(
                f"  ADR-{n:04d}  (no local file {g.cfg.adr_dir}/{n:04d}-*.md)"
            )
            continue
        for m in matches:
            fm = (
                parse_frontmatter(m.read_text(encoding="utf-8", errors="replace"))
                or {}
            )
            if fm.get("status") == "stub" and fm.get("points-to"):
                out.append(f"  {rel(m)}  → upstream: {fm['points-to']}")
            else:
                out.append(f"  {rel(m)}  (local)")
    if not adr_nums:
        out.append("  (no ADR-NNNN cited)")
    out.append("")

    out.append("TIER 5  source docs (the epic's declared provenance)")
    src_entries: list[tuple[str, str]] = []
    if epic_doc.exists():
        fm2 = (
            parse_frontmatter_full(
                epic_doc.read_text(encoding="utf-8", errors="replace")
            )
            or {}
        )
        for entry in fm2.get("source_docs") or []:
            if isinstance(entry, str):
                src_entries.append(("local", entry.strip()))
            elif isinstance(entry, dict) and len(entry) == 1:
                ((scheme, path),) = entry.items()
                src_entries.append((str(scheme).strip(), str(path).strip()))
    for scheme, p in src_entries:
        if scheme == "url":
            out.append(f"  url         {p}")
        elif scheme in g.cfg.siblings:
            tgt = g.cfg.sibling_path(scheme) / p
            flag = "" if tgt.exists() else "   (NOT checked out)"
            out.append(f"  {scheme:<9}   {g.cfg.siblings[scheme]}/{p}{flag}")
        else:  # local (or bare, normalised to 'local')
            flag = "" if (root / p).exists() else "   (MISSING)"
            out.append(f"  {scheme:<9}   {p}{flag}")
    if not src_entries:
        out.append("  (epic carries no source_docs:)")
    out.append("")

    out.append(
        f"→ READ every path above (and the named register rows) before "
        f"starting {scope}."
    )
    print("\n".join(out))
    return 0
