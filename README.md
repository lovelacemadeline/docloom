# docloom

A portable documentation-conventions gauntlet, extracted from the
crosssense-v3-server doc system. Typed frontmatter, a sprint tracker with
enforced tracker↔file bijection, citeable self-describing registers, and
spec-grounding anchors that tie stories to real code — packaged so any project
gets the whole system in one command.

## Install & bootstrap

```bash
uv tool install --from /path/to/docloom docloom   # or git+… once hosted
cd my-project
docloom init            # scaffolds docs/, conventions, tracker, pre-commit, CC skill
docloom check           # the gauntlet — wire into pre-commit + CI
docloom context 26.1    # tiered path manifest of every doc related to a story/epic
```

`init` is idempotent and never overwrites existing files. Use
`docloom init --advisory` on a brownfield project to start Gate 3 (anchors)
advisory-only, then flip `gate3.enforced = true` in `docloom.toml` once the
retrofit lands (the same ratchet pattern the original repo used).

## `context` — the doc-graph traversal

`docloom context <epic-or-story>` (e.g. `26`, `epic-26`, `26.1`) prints a
tiered path manifest for a "thing to be done": the epic doc, its story files,
every discovered register whose clauses the epic owns or the story cites (with
row ids), cited ADRs (stubs list their upstream `points-to:`), and the epic's
`source_docs:` provenance. The scaffolded Claude Code skill instructs agents to
run it and read every emitted path before starting work.

## What `check` enforces

- **Gate 1 — Doc validity**: every `.md` carries `type:` (12 closed values) +
  `status:` (8 closed values, or the execution-state axis for epic/story);
  frontmatter is real YAML; relative links resolve.
- **Gate 2 — Consistency & tracking**: epic/story number identity, the
  tracker↔file bijection + title agreement, registry citations
  (`ADR-NNNN`, clause ids) resolve, orphan + completion-coverage checks over
  every discovered clause register.
- **Gate 3 — Spec-grounding anchors**: in-scope stories name real
  `symbol:`/`test:`/`route:` artifacts (or `anchor: none # reason`); a
  `completed` story whose anchors don't resolve is a hard fail.
- **Advisories** (never fail the build): epic `source_docs:` dangles, register
  thinness (restated shapes/versions), unowned clause families.

## Design

- **Config over hardcoding** — every repo-specific constant of the original
  checker (paths, vocabulary, ratchets, sibling checkouts) lives in
  `docloom.toml` / `[tool.docloom]`. See `examples/crosssense.toml`, which
  reproduces the original repo's behavior exactly.
- **Self-describing by default** — clause registers declare their own
  `register:` spec block, and the conventions doc's `vocabulary:` frontmatter
  block is the authoritative enum source (`vocabulary.from-doc`, active from
  `init`): the doc agents read IS the spec the checker enforces. Its prose
  tables are agreement-checked against the block, and a missing/mangled block
  is a hard error — never a silent fallback to defaults. Tool-version facts
  (the sub-check list) are deliberately NOT restated per-repo: `docloom check`
  output is their authoritative enumeration.
- **Pluggable anchor resolvers** — `python` (stdlib-ast symbols/tests) and
  `litestar` (route composition) ship in v1; other languages/frameworks are
  registered stubs that fail loudly rather than silently passing.

## Parity against the original

`parity/run_parity.sh` runs both the original
`scripts/check_doc_conventions.py` and `docloom check` (with the crosssense
config) from the crosssense repo root, in all three modes (strict, `--summary`,
`--valid-if-present`), and byte-diffs the outputs + exit codes.

## Status

v0.3 — adds `docloom context` (the tiered doc-graph manifest). The crosssense repo still runs its own in-tree
checker; nothing there depends on this package yet.
