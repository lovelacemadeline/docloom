---
type: guide
status: active
title: Documentation Conventions — the single source of truth for how we write docs
owner: {{PROJECT}}
---

# Documentation Conventions

> **This is the canonical source of truth for how documentation works in
> `{{PROJECT}}`.** Every `.md` file in this repo follows it. Before you create,
> rename, move, or re-purpose any document — read this. Do **not** invent a new
> doc "kind", status word, or ad-hoc label; if something doesn't fit, split it
> (§6), don't add a new type. Enforced by `docloom check` (pre-commit + CI).

## 1. Every doc carries two frontmatter fields

Two **orthogonal** required fields, both closed enums so they can be
machine-checked:

- **`type:`** — *what kind of thing this is.* One of the 12 values in §2.
  Immutable for the life of the doc.
- **`status:`** — *how much to trust it today.* One of the 8 values in §3.
  Changes over time.

"Archived", "parked", "superseded", "stub" are **statuses, not types and not
directories**. A document's **`type:` implies its home directory** (§2) —
directories are a *consequence* of type, so `docs/` never becomes a junk drawer.

## 2. The `type:` vocabulary (closed — 12 values)

| `type:` | What it is | Canonical home | Naming |
|---|---|---|---|
| `prd` | Product/feature requirements — the *what & why* | `docs/product/` | `prd-<slug>.md` |
| `epic` | One epic's scope + its story list | `docs/epics/` | `epic-NN.md` |
| `story` | One story spec + acceptance criteria | `docs/stories/` | `NN-Mx-<slug>.md` |
| `register` | **The citeable spine** — a canonical enumeration other docs cite by ID | `docs/reference/`, `docs/epics/index.md` | `<slug>-register.md` |
| `decision` | One ratified decision + provenance + rejected alternatives (ADR) | `docs/adr/` | `NNNN-<slug>.md` |
| `reference` | Evergreen *descriptive* fact: architecture, API, dataflow | `docs/reference/` | `<slug>.md` |
| `guide` | Prescriptive *how-to / conventions* (this file, dev setup, agent rules) | repo root + `docs/` | `<slug>.md` |
| `runbook` | Operational step-by-step: deploy, bring-up, recover | `docs/runbooks/` | `<slug>.md` |
| `plan` | Forward-looking roadmap **not yet decomposed into epics** | `docs/` | `NN-<slug>.md` |
| `research` | Time-boxed investigation — an *input*, never authoritative | `docs/research/` | `<slug>-YYYY-MM.md` |
| `snapshot` | True only *as of its date*: readiness reports, handovers | `docs/status/` | `<slug>-YYYY-MM-DD.md` |
| `working-artifact` | Temporary scaffolding; **deleted before merge** | anywhere | `<SLUG>-YYYY-MM-DD.md` |

## 3. The `status:` vocabulary (closed — 8 values)

| `status:` | Meaning | Conditional field |
|---|---|---|
| `draft` | Being written; not yet authoritative | — |
| `active` | Current and authoritative | — |
| `superseded` | Replaced; kept for history | **`superseded-by:`** (required) |
| `parked` | Real but paused; not being maintained | — |
| `archived` | Frozen historical record; do not update | — |
| `snapshot` | Point-in-time; never updated after its date | — |
| `stub` | Pointer to an upstream/canonical source | **`points-to:`** (required) |
| `temporary` | Scaffolding to be deleted before merge | — |

**`epic` / `story` use a second, closed status axis: execution state** —
`status:` on those two types means *how far the work has got*:

`pending` · `ready-for-dev` · `in-progress` · `blocked` · `needs-refactoring`
· `superseded` · `completed` · `deferred`

## 4. The frontmatter contract

```yaml
---
type: story               # one of the 12 (§2)
status: in-progress       # lifecycle (§3) or execution state for epic/story
title: Human-readable title
owner: <name>
updated: YYYY-MM-DD       # last meaningful review date — not git noise
# conditional:
superseded-by: <path>     # required iff status: superseded
points-to: <url|path>     # required iff status: stub
---
```

## 5. Sub-conventions

### 5.1 `register` — cite by ID, never restate
A register *owns* a set of facts (epic numbers, requirement clauses, versions).
Everything else **cites it by ID** rather than copying the value — duplicated
facts are how drift starts. A **clause register** (owning an id family like
`C-CORE-*`) declares a machine-readable `register:` frontmatter block; the
checker discovers every such doc and runs the same generic checks over each —
adding a register is *adding a conforming doc*, never a checker edit:

```yaml
register:
  name: core                          # label used in check messages
  clause-prefixes: [C-CORE]           # required — id families this register owns
  crosscutting-prefixes: [NFR-CORE]   # optional — resolve-only (no orphan/coverage)
  enactable-glyphs: ["🔴", "🟡", "🟢"] # optional — glyphs marking real work
  proposed: []                        # optional — pending ids, exempt from checks
  owner-map:                          # optional — enables completion-coverage
    heading: "### Coverage Map"
    until: "## Notes"
    line: '- \*\*Epic (\d+):\*\*'
```

Body format the parser reads: each clause on its own line as
`- **<ID>** <glyphs> — <description>`.

### 5.2 `decision` — ADRs live in `docs/adr/`
Numbered `NNNN-<slug>.md`; allocate from the ledger in `docs/adr/index.md`.
Upstream decisions get a local `status: stub` pointer so every `ADR-NNNN`
citation resolves to a real local file.

### 5.3 `epic` — unique number, stories in their own files
Every epic doc carries `epic: N` matching its `epic-NN.md` filename; allocate
numbers from the registry in `docs/epics/index.md`. Each story gets its own
file under `docs/stories/` (`NN-Mx-<slug>.md`, `type: story`); the epic keeps
only a high-level `## Stories` table. When you add a story, add its tracker row
in the same change (§7).

## 6. Allocating a new document
1. Pick the `type:` from §2. If nothing fits, the doc is probably **two types
   fused** — split it. Don't add a 13th type without changing this doc first.
2. Put it in the type's canonical home; give it the frontmatter contract (§4).
3. Stories and ADRs move together with their registries (§7).

## 7. Enforcement — three gates (`docloom check`)

**Gate 1 — Doc validity**: every doc's `type:`/`status:` present and
enum-valid; frontmatter is real YAML; relative links resolve.

**Gate 2 — Consistency & tracking**: epic/story numbers are collision-free and
homed; every `docs/sprint-status.yaml` story row exists on disk with a matching
status and title, and every story file has a tracker row (the bijection);
registry citations (`ADR-NNNN`, clause ids) resolve; enactable clauses are
cited by at least one doc (orphan check); completed epics account for every
clause they own; epic doc status equals its tracker status.

**Gate 3 — Spec-grounding anchors**: every in-scope story carries an `anchor:`
list — concrete code artifacts whose existence is checked mechanically — or the
explicit opt-out `anchor: none  # <reason>`:

```yaml
anchor:
  - symbol: "src/pkg/module.py::ClassName"       # dotted ::Class.method ok
  - test:   "tests/test_module.py::test_invariant"
  - route:  "GET /api/v1/things"
```

> **Anchors are a tripwire for *absence*, never a proof of *done*.** A
> `completed` story whose anchors don't all resolve is a hard fail — the
> "marked done, but the named thing isn't there" lie. Semantic correctness
> stays with the test suite.

**The enforced-interim pattern**: when a story ships a stopgap for work another
story owns, don't leave a bare TODO — add a *target* anchor (the test that only
passes once the stopgap is gone) to the story that owns the real
implementation, and note the seam where the interim lives. The owning story
then can't reach `completed` while the stopgap survives.
