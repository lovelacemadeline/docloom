---
name: docloom
description: Record dev work as governed docs — epics, stories with spec-grounding anchors, tracker rows — and keep them passing `docloom check`. Use when asked to "record what we've built", "docloom this", "write up this work as stories", or before committing doc changes.
---

# docloom — record work as governed documentation

This project's docs follow `docs/doc-conventions.md` (typed frontmatter, a
sprint tracker, citeable registers, spec-grounding anchors), enforced by
`docloom check`. Read that file first if you haven't this session.

## Recording a rabbit-hole (retro-documenting built work)

When asked to record work that already exists (the "we built a ton of stuff
with no docs" case):

1. **Inventory** what was actually built: entry points, key symbols, tests,
   routes. `git log --oneline` + the diff vs the starting point is the honest
   source; do not document intentions, document artifacts.
2. **Allocate an epic**: add a row to `docs/epics/index.md`, create
   `docs/epics/epic-NN.md` (`type: epic`, `epic: NN`, execution `status:`).
3. **One story file per coherent chunk** in `docs/stories/NN-M-<slug>.md`
   (`type: story`), each with:
   - `## Acceptance Criteria` in given/when/then form (what the code actually
     does now, not aspiration);
   - an `anchor:` list pointing at the REAL symbols/tests that exist —
     `symbol: "src/x.py::Thing"`, `test: "tests/test_x.py::test_invariant"` —
     or `anchor: none  # <reason>` for genuinely surfaceless work;
   - `status: completed` only if its anchors resolve AND tests exist; work
     without a pinning test is `in-progress` or `needs-refactoring`, not done.
4. **Tracker rows**: add each story under its epic in
   `docs/sprint-status.yaml` with the SAME id, title, and status as the file
   (the bijection check enforces this).
5. **Future work discussed but not built** becomes `status: pending` /
   `ready-for-dev` stories (or a `type: plan` doc if not yet decomposed) — this
   is how "stuff we talked about" survives the session.
6. **Run `docloom check`** and fix everything it flags before committing.

## Rules that bite

- Never invent a new `type:` or status word — the enums are closed.
- A story is `completed` only when every anchor resolves; anchors are a
  tripwire for absence, never proof of done.
- Stopgaps: pin retirement with a target anchor on the story that owns the
  real fix (see §7 of the conventions doc), never a bare TODO.
- Cite symbols, not line numbers (`get_node_by_id`, not `queries.py:288`).
