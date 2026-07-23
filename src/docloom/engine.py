"""The gauntlet engine — a faithful port of crosssense-v3-server's
``scripts/check_doc_conventions.py``, with every repo-specific constant lifted
into :class:`docloom.config.Config` and anchor resolution delegated to the
pluggable resolvers. Check semantics, issue-message wording, and ordering are
preserved deliberately, so the port can be parity-tested byte-for-byte against
the original's output on the same corpus.
"""

from __future__ import annotations

import functools
import re
from pathlib import Path

import yaml

from . import gitio
from .config import Config
from .frontmatter import parse_frontmatter, parse_frontmatter_full, strip_frontmatter
from .resolvers import get_route_resolver, get_symbol_resolver

# Generic clause / NFR *shape* detectors (ANY family, not just registered ones).
_ADR_CITE = re.compile(r"\bADR-(\d+)\b")
_CLAUSE_CITE = re.compile(r"\bC-[A-Z]+-\d+\b")
_NFR_CITE = re.compile(r"\bNFR-[A-Z]+-\d+\b")
_CLAUSE_FAMILY = re.compile(r"\b(C-[A-Z]+)-\d+\b")
_NFR_FAMILY = re.compile(r"\b(NFR-[A-Z]+)-\d+\b")

_REG_VER = re.compile(r"\bv\d+\.\d+(?:\.\d+)?\b")
_REG_BRACE = re.compile(r"\{[^{}\n]*[,=][^{}\n]*\}")

_WRAPPED = ("completed", "deferred")


def _prefix_re(prefixes: list[str]) -> re.Pattern[str]:
    r"""A ``\bC-AUTH-\d+\b``-style matcher for a register's declared id prefixes."""
    alt = "|".join(re.escape(p) for p in prefixes)
    return re.compile(rf"\b(?:{alt})-\d+\b")


class RegisterSpec:
    """One clause register, built from a `type: register` doc's `register:`
    frontmatter block. Every field a check needs is declared here, so no check
    function hardcodes a path, id scheme, glyph, or layout for any one register."""

    def __init__(
        self,
        *,
        name: str,
        path: Path,
        clause_prefixes: tuple[str, ...],  # enactable-capable families it owns
        crosscut_prefixes: tuple[str, ...],  # NFR-like: resolve-only (no orphan/cov)
        clause_re: re.Pattern[str],
        crosscut_re: re.Pattern[str] | None,
        enactable_glyphs: tuple[str, ...],  # glyphs marking work; () => no enactability
        proposed: frozenset[str],  # ids pending upstream; exempt from resolve + orphan
        owner_heading: str | None,  # coverage-map section start (enables ownership)
        owner_until: str | None,  # coverage-map section end (optional)
        owner_line: re.Pattern[str] | None,  # owner line; group(1) = epic number
    ) -> None:
        self.name = name
        self.path = path
        self.clause_prefixes = clause_prefixes
        self.crosscut_prefixes = crosscut_prefixes
        self.clause_re = clause_re
        self.crosscut_re = crosscut_re
        self.enactable_glyphs = enactable_glyphs
        self.proposed = proposed
        self.owner_heading = owner_heading
        self.owner_until = owner_until
        self.owner_line = owner_line


class Gauntlet:
    """One check run over one project root. Instances memoize corpus reads for
    the lifetime of the run (the moral equivalent of the original's module-level
    ``functools.cache``)."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.root = cfg.root
        self._symbols = get_symbol_resolver(cfg.symbol_resolver)
        self._routes = get_route_resolver(cfg.route_resolver)

    # -- corpus ----------------------------------------------------------------

    @functools.cached_property
    def docs(self) -> list[Path]:
        return gitio.tracked_markdown(self.root, self.cfg.exclude_prefixes)

    def _rel(self, path: Path) -> str:
        return str(path.relative_to(self.root))

    def _last_commit_date(self, rel: str) -> str:
        return gitio.last_commit_date(self.root, rel)

    # -- Gate 1: per-doc frontmatter validity -----------------------------------

    def check_doc(self, path: Path, valid_if_present: bool) -> list[str]:
        """Return a list of violation strings for one doc (empty == compliant)."""
        cfg = self.cfg
        fm = parse_frontmatter(path.read_text(encoding="utf-8", errors="replace"))

        if fm is None or "type" not in fm:
            return [] if valid_if_present else ["no frontmatter / missing type:"]

        violations: list[str] = []
        if fm["type"] not in cfg.types:
            violations.append(f"invalid type: {fm['type']!r}")

        if "status" not in fm:
            violations.append("missing status:")
        elif fm["type"] in ("epic", "story"):
            if fm["status"] not in cfg.execution_statuses:
                violations.append(f"invalid execution status: {fm['status']!r}")
        elif fm["status"] not in cfg.statuses:
            violations.append(f"invalid status: {fm['status']!r}")
        else:
            required = cfg.conditional.get(fm["status"])
            if required and required not in fm:
                violations.append(f"status: {fm['status']} requires '{required}:'")
        return violations

    def frontmatter_yaml_issues(self) -> list[str]:
        """Every doc that *looks* like it has a real frontmatter block must
        `yaml.safe_load` to a mapping."""
        issues: list[str] = []
        for path in self.docs:
            text = path.read_text(encoding="utf-8", errors="replace")
            if not text.startswith("---"):
                continue
            lines = text.splitlines()
            end = next(
                (i for i in range(1, len(lines)) if lines[i].strip() == "---"), None
            )
            if end is None:
                continue  # unterminated block is Gate-1's frontmatter check's job
            if any(re.match(r"^#{1,6}\s", lines[i]) for i in range(1, end)):
                continue  # not a real frontmatter block (heading before the close)
            rel = path.relative_to(self.root)
            try:
                data = yaml.safe_load("\n".join(lines[1:end]))
            except yaml.YAMLError as exc:
                first = str(exc).splitlines()[0] if str(exc) else "parse error"
                issues.append(f"{rel}: frontmatter is not valid YAML — {first}")
                continue
            if not isinstance(data, dict):
                issues.append(f"{rel}: frontmatter is not a YAML mapping")
        return issues

    def _story_status_value(self, text: str) -> str | None:
        """Leading token of a story file's plain `Status:` body line, lowercased."""
        for line in text.splitlines()[:15]:
            m = re.match(r"^\*{0,2}Status:?\*{0,2}\s*(.+?)\s*$", line)
            if m:
                return re.split(r"[\s(#]", m.group(1).strip("* "))[0].lower()
        return None

    def story_status_issues(self) -> list[str]:
        """INTERIM gate: validate untyped story files' plain `Status:` body line
        against the execution enum. Once a story gains `type: story` frontmatter,
        the frontmatter check governs it and this body-line check skips it."""
        issues: list[str] = []
        for path in sorted(self.cfg.stories_path.glob("*.md")):
            text = path.read_text(encoding="utf-8", errors="replace")
            fm = parse_frontmatter(text)
            if fm and "type" in fm:
                continue  # typed -> governed by the frontmatter check
            rel = self._rel(path)
            val = self._story_status_value(text)
            if val is None:
                issues.append(f"{rel}: no Status: line")
            elif val not in self.cfg.execution_statuses:
                issues.append(f"{rel}: invalid Status: {val!r}")
        return issues

    def dangling_link_issues(self) -> list[str]:
        """Flag Markdown links whose repo-relative target doesn't resolve."""
        link_re = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
        issues: list[str] = []
        for path in self.docs:
            text = path.read_text(encoding="utf-8", errors="replace")
            fm = parse_frontmatter(text)
            if fm and fm.get("status") == "archived":
                continue
            # Strip fenced + inline code so code like `d[k](**kw)` isn't a link.
            scan = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
            scan = re.sub(r"`[^`]*`", "", scan)
            rel = self._rel(path)
            for m in link_re.finditer(scan):
                target = m.group(1).split("#", 1)[0].strip()
                if not target:
                    continue  # pure #anchor
                if re.match(r"^[a-z][a-z0-9+.-]*://", target):
                    continue  # scheme URL (http/https/ssh/…)
                if target.startswith(("mailto:", "git@", "/")):
                    continue  # email / git-ssh / absolute or IPA notation
                if "/" not in target and "." not in target:
                    continue  # not path-like (inline maths/refs, not a file link)
                candidates = [
                    path.parent / target,
                    self.root / target,
                    self.root / "docs" / target,
                ]
                if not any(c.exists() for c in candidates):
                    issues.append(f"{rel}: dangling link -> {m.group(1)}")
        return issues

    def conventions_doc_issues(self) -> list[str]:
        """Doc-internal agreement for the self-describing conventions doc: the
        values enumerated in its prose vocabulary tables must equal its
        authoritative `vocabulary:` frontmatter block — the same move as the
        tracker<->file bijection, applied to the conventions doc itself. The
        tables are what agents READ; the block is what the checker ENFORCES;
        this gate is what keeps them the same artifact. Only runs when
        `vocabulary.from-doc` is configured.

        Tables are classified by their header row's first cell (contains
        "execution" -> execution statuses; else "type" -> types; else "status"
        -> statuses) and values are read from backticked first-column cells —
        deliberately keyed on structure the shipped template controls, not a
        general Markdown-table parser."""
        rel = self.cfg.vocab_from_doc
        if rel is None:
            return []
        doc = self.root / rel
        if not doc.exists():  # config load already hard-fails; belt-and-braces
            return [f"{rel}: vocabulary.from-doc target missing"]
        text = strip_frontmatter(doc.read_text(encoding="utf-8", errors="replace"))
        # Strip fenced code so example frontmatter blocks can't read as tables.
        text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)

        found: dict[str, set[str]] = {}
        header: str | None = None
        past_separator = False
        for line in text.splitlines():
            if not line.lstrip().startswith("|"):
                header, past_separator = None, False
                continue
            first_cell = line.split("|")[1].strip() if "|" in line[1:] else ""
            if header is None:
                h = first_cell.lower()
                if "execution" in h and "status" in h:
                    header = "execution statuses"
                elif "type" in h:
                    header = "types"
                elif "status" in h:
                    header = "statuses"
                else:
                    header = "ignored"
                continue
            if not past_separator:
                past_separator = True  # the |---|---| row
                continue
            if header != "ignored" and (m := re.match(r"^`([^`]+)`", first_cell)):
                found.setdefault(header, set()).add(m.group(1))

        expected = {
            "types": set(self.cfg.types),
            "statuses": set(self.cfg.statuses),
            "execution statuses": set(self.cfg.execution_statuses),
        }
        issues: list[str] = []
        for axis, want in expected.items():
            got = found.get(axis)
            if got is None:
                issues.append(f"{rel}: no {axis} table found to agree with the block")
                continue
            for extra in sorted(got - want):
                issues.append(
                    f"{rel}: {axis} table lists {extra!r} — absent from the "
                    "`vocabulary:` block"
                )
            for missing in sorted(want - got):
                issues.append(
                    f"{rel}: `vocabulary:` block declares {missing!r} — missing "
                    f"from the {axis} table"
                )
        return issues

    # -- Gate 2: epic/story identity + tracker reconciliation --------------------

    def epic_number_issues(self, docs: list[Path]) -> list[str]:
        """Detect epic-number collisions, mislocated epics, filename mismatches."""
        epics_rel = self.cfg.epics_dir.rstrip("/") + "/"
        by_number: dict[str, list[str]] = {}
        issues: list[str] = []
        for path in docs:
            rel = self._rel(path)
            fm = parse_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
            if not fm:
                continue
            typed_epic = fm.get("type") == "epic"
            in_home = rel.startswith(epics_rel)
            legacy_epic = in_home and "type" not in fm and "epic" in fm
            if not (typed_epic or legacy_epic):
                continue
            if typed_epic and not in_home:
                issues.append(f"{rel}: type: epic but outside its home {epics_rel}")
            if "epic" not in fm:
                issues.append(f"{rel}: type: epic but no 'epic:' number")
                continue
            num = fm["epic"].strip()
            by_number.setdefault(num, []).append(rel)
            m = re.search(r"epic-(\d+)\.md$", path.name)
            if m and m.group(1).lstrip("0") != num.lstrip("0"):
                issues.append(
                    f"{rel}: filename epic-{m.group(1)} vs frontmatter epic: {num}"
                )
        for num, paths in sorted(by_number.items()):
            if len(paths) > 1:
                annotated = ", ".join(
                    f"{p} (last edited {self._last_commit_date(p)})" for p in paths
                )
                issues.append(
                    f"epic number {num} claimed by {len(paths)} docs: {annotated}"
                )
        return issues

    def sprint_status_issues(self) -> list[str]:
        """Validate every status in the sprint tracker against the execution enum."""
        tracker = self.cfg.tracker_path
        if not tracker.exists():
            return []
        data = yaml.safe_load(tracker.read_text(encoding="utf-8")) or {}
        issues: list[str] = []
        for epic in data.get("epics", []):
            es = epic.get("status")
            if es not in self.cfg.execution_statuses:
                issues.append(f"tracker epic {epic.get('epic')}: invalid status {es!r}")
            for story in epic.get("stories") or []:
                ss = story.get("status")
                if ss not in self.cfg.execution_statuses:
                    issues.append(
                        f"tracker story {story.get('id')}: invalid status {ss!r}"
                    )
        return issues

    @functools.cached_property
    def _tracker_epics(self) -> list[dict]:
        """The `epics:` list from the sprint tracker (empty if absent/malformed)."""
        tracker = self.cfg.tracker_path
        if not tracker.exists():
            return []
        data = yaml.safe_load(tracker.read_text(encoding="utf-8")) or {}
        return data.get("epics", []) or []

    def _epic_doc(self, epic_num: object) -> Path:
        """Epic-doc path for an epic number. Zero-padded `epic-NN.md` is the
        canonical name, but unpadded `epic-N.md` is equally valid (the filename
        gate compares numbers with padding stripped) — so whichever exists wins,
        else canonical. Without this, an unpadded repo reads as MISSING in the
        context manifest and silently skips the epic<->tracker status check."""
        n = int(epic_num)
        padded = self.cfg.epics_path / f"epic-{n:02d}.md"
        unpadded = self.cfg.epics_path / f"epic-{n}.md"
        if not padded.exists() and unpadded.exists():
            return unpadded
        return padded

    def _inline_story_ids(self, doc: Path) -> list[str]:
        """Story ids from `## Story N.M[x]` headings in an inline epic doc."""
        if not doc.exists():
            return []
        ids: list[str] = []
        for line in doc.read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.match(r"^#{2,}\s+Story\s+(\d+\.\d+[a-z]?)\b", line)
            if m:
                ids.append(m.group(1))
        return ids

    def _story_files_for_epic(self, epic_num: object) -> list[Path]:
        return sorted(self.cfg.stories_path.glob(f"{epic_num}-*.md"))

    def _file_story_id(self, path: Path) -> str:
        """A story file's id: its `story:` frontmatter if typed, else the filename."""
        fm = parse_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
        if fm and "story" in fm:
            return fm["story"].strip().strip('"')
        parts = path.name[:-3].split("-")
        return f"{parts[0]}.{parts[1]}"

    def _story_files_for_id(self, sid: str) -> list[Path]:
        """Story file(s) whose id derives to `sid` (e.g. `8.2a` -> `8-2a-*.md`)."""
        epic, mx = sid.split(".", 1)
        return sorted(self.cfg.stories_path.glob(f"{epic}-{mx}-*.md"))

    @functools.cached_property
    def _tracker_story_rows(self) -> dict[str, dict[str, object]]:
        """Every tracker story row keyed by id (last write wins on the rare dup)."""
        return {
            s["id"]: s
            for e in self._tracker_epics
            for s in (e.get("stories") or [])
            if s.get("id")
        }

    def _exempt_map(self, raw: object) -> dict[str, str]:
        """A `conventions-exempt:` value normalized to {check: reason}, keeping
        only well-formed `str: str` pairs."""
        if not isinstance(raw, dict):
            return {}
        return {
            k: v for k, v in raw.items() if isinstance(k, str) and isinstance(v, str)
        }

    @functools.cache
    def _story_exemptions(self, sid: str) -> set[str]:
        """The set of checks story `sid` is exempt from — declared as
        `conventions-exempt: {check: reason}` on its story file frontmatter OR its
        tracker row."""
        checks: set[str] = set()
        for f in self._story_files_for_id(sid):
            fm = parse_frontmatter_full(
                f.read_text(encoding="utf-8", errors="replace")
            )
            checks |= set(self._exempt_map((fm or {}).get("conventions-exempt")))
        row = self._tracker_story_rows.get(sid)
        if row is not None:
            checks |= set(self._exempt_map(row.get("conventions-exempt")))
        return checks

    def _validate_exempt(self, raw: object, where: str) -> list[str]:
        """Validate one `conventions-exempt:` declaration."""
        if raw is None:
            return []
        if not isinstance(raw, dict):
            return [f"{where}: conventions-exempt must be a map of check: reason"]
        issues: list[str] = []
        for k, v in raw.items():
            if k not in self.cfg.exemptable_checks:
                issues.append(
                    f"{where}: conventions-exempt unknown check {k!r} "
                    f"(allowed: {sorted(self.cfg.exemptable_checks)})"
                )
            if not (isinstance(v, str) and v.strip()):
                issues.append(f"{where}: conventions-exempt[{k!r}] needs a reason")
        return issues

    def conventions_exempt_issues(self) -> list[str]:
        """Gate-1 validity of the exemption escape hatch itself."""
        issues: list[str] = []
        for f in sorted(self.cfg.stories_path.glob("*.md")):
            fm = parse_frontmatter_full(
                f.read_text(encoding="utf-8", errors="replace")
            )
            issues += self._validate_exempt((fm or {}).get("conventions-exempt"), f.name)
        for sid, row in self._tracker_story_rows.items():
            where = f"tracker story {sid}"
            issues += self._validate_exempt(row.get("conventions-exempt"), where)
        return issues

    def story_number_issues(self) -> list[str]:
        """Detect story-number collisions — the story-level analogue of the epic
        guard, keyed off each tracker epic's declared `story_home`."""
        by_id: dict[str, list[str]] = {}
        for epic in self._tracker_epics:
            home = epic.get("story_home")
            num = epic.get("epic")
            if home == "inline":
                doc = self._epic_doc(num)
                rel = self._rel(doc)
                for sid in self._inline_story_ids(doc):
                    by_id.setdefault(sid, []).append(rel)
            elif home == self.cfg.stories_dir.rstrip("/") + "/":
                for f in self._story_files_for_epic(num):
                    by_id.setdefault(self._file_story_id(f), []).append(self._rel(f))
        issues: list[str] = []
        for sid, srcs in sorted(by_id.items()):
            if len(srcs) > 1 and "story-id" not in self._story_exemptions(sid):
                annotated = ", ".join(
                    f"{s} (last edited {self._last_commit_date(s)})" for s in srcs
                )
                issues.append(
                    f"story id {sid} claimed by {len(srcs)} sources: {annotated}"
                )
        return issues

    @staticmethod
    def _is_qa_handover(story: dict) -> bool:
        """A QA/Handover process row (not a code story) — exempt from bijection."""
        title = (story.get("title") or "").lower()
        return "qa" in title and "handover" in title

    def bijection_issues(self) -> list[str]:
        """Reconcile the tracker's per-story rows with their on-disk location
        (forward per epic; reverse GLOBAL over every story file)."""
        stories_home = self.cfg.stories_dir.rstrip("/") + "/"
        issues: list[str] = []
        all_tracker_ids = {
            s.get("id")
            for epic in self._tracker_epics
            for s in (epic.get("stories") or [])
        }
        for epic in self._tracker_epics:
            stories = epic.get("stories") or []
            if not stories:
                continue  # no per-story rows -> forward/inline checks: nothing to do
            home = epic.get("story_home")
            num = epic.get("epic")
            doc = self._epic_doc(num)
            inline_ids = set(self._inline_story_ids(doc)) if home == "inline" else set()
            tracker_ids: set[str] = set()

            # forward: tracker -> disk
            for s in stories:
                sid = s.get("id")
                tracker_ids.add(sid)
                if (
                    "bijection" in self._story_exemptions(sid)
                    or self._is_qa_handover(s)
                    or s.get("status") == "superseded"
                ):
                    continue
                if home == "inline":
                    if sid not in inline_ids:
                        issues.append(
                            f"tracker story {sid}: no '## Story {sid}' heading in "
                            f"{self._rel(doc)}"
                        )
                elif home == stories_home:
                    files = self._story_files_for_id(sid)
                    if not files:
                        issues.append(
                            f"tracker story {sid}: no story file under {stories_home}"
                        )
                        continue
                    fm = parse_frontmatter(
                        files[0].read_text(encoding="utf-8", errors="replace")
                    )
                    fst = (fm or {}).get("status")
                    if fst != s.get("status"):
                        issues.append(
                            f"tracker story {sid}: status {s.get('status')!r} != "
                            f"file status {fst!r} ({files[0].name})"
                        )

            # reverse (inline only): every inline heading has a tracker row.
            if home == "inline":
                for sid in inline_ids:
                    if sid not in tracker_ids and "bijection" not in (
                        self._story_exemptions(sid)
                    ):
                        issues.append(
                            f"inline story {sid} in {doc.name}: no matching tracker row"
                        )

        # reverse (GLOBAL): every story file on disk must map to a tracker row.
        for f in sorted(self.cfg.stories_path.glob("*.md")):
            sid = self._file_story_id(f)
            if sid not in all_tracker_ids and "bijection" not in (
                self._story_exemptions(sid)
            ):
                issues.append(
                    f"story file {f.name} (id {sid}): no matching tracker row in "
                    f"{self.cfg.tracker_path.name}"
                )
        return issues

    @staticmethod
    def _norm_title(s: object) -> str:
        """Case- and whitespace-insensitive normalization for title comparison."""
        return re.sub(r"\s+", " ", str(s or "").strip()).casefold()

    def title_issues(self) -> list[str]:
        """Every story file's `title:` must agree with its tracker row's title
        (normalized: case + whitespace insensitive)."""
        rows = {
            s.get("id"): s
            for epic in self._tracker_epics
            for s in (epic.get("stories") or [])
        }
        issues: list[str] = []
        for f in sorted(self.cfg.stories_path.glob("*.md")):
            sid = self._file_story_id(f)
            row = rows.get(sid)
            if (
                row is None
                or "title" in self._story_exemptions(sid)
                or self._is_qa_handover(row)
                or row.get("status") == "superseded"
            ):
                continue
            ftitle = (
                parse_frontmatter(f.read_text(encoding="utf-8", errors="replace"))
                or {}
            ).get("title")
            if ftitle is None:
                continue
            if self._norm_title(ftitle) != self._norm_title(row.get("title")):
                issues.append(
                    f"story file {f.name} (id {sid}): title {ftitle!r} != tracker "
                    f"title {row.get('title')!r}"
                )
        return issues

    def epic_status_consistency_issues(self) -> list[str]:
        """An epic marked `completed` must have every story `completed` or
        `deferred`."""
        issues: list[str] = []
        for epic_doc in sorted(self.cfg.epics_path.glob("epic-*.md")):
            fm = parse_frontmatter(
                epic_doc.read_text(encoding="utf-8", errors="replace")
            )
            if not fm or fm.get("status") != "completed":
                continue
            num = epic_doc.stem.split("-")[1].lstrip("0") or "0"
            wip = []
            for sf in sorted(self.cfg.stories_path.glob(f"{num}-*.md")):
                st = (
                    parse_frontmatter(sf.read_text(encoding="utf-8", errors="replace"))
                    or {}
                ).get("status")
                if st not in _WRAPPED:
                    wip.append(f"{sf.name} ({st})")
            if wip:
                issues.append(
                    f"epic {num} marked completed but has non-terminal stories: {wip}"
                )
        return issues

    def epic_status_tracker_issues(self) -> list[str]:
        """Epic-level bijection: each epic doc's `status:` frontmatter must equal
        its tracker epic-level `status:`."""
        issues: list[str] = []
        for ep in self._tracker_epics:
            num = ep.get("epic")
            tst = ep.get("status")
            if num is None or tst is None:
                continue
            doc = self._epic_doc(num)
            if not doc.exists():
                continue
            fm = parse_frontmatter(doc.read_text(encoding="utf-8", errors="replace"))
            dst = (fm or {}).get("status")
            if dst is not None and dst != tst:
                issues.append(
                    f"epic {num}: doc status {dst!r} != tracker status {tst!r}"
                )
        return issues

    # -- Gate 3: story spec-grounding anchors ------------------------------------

    @functools.cached_property
    def _route_set(self) -> frozenset[tuple[str, str]]:
        return self._routes.route_set(self.root, self.cfg.route_globs)

    def _anchor_present(self, kind: str, val: str) -> bool:
        if kind == "symbol":
            rel, _, name = val.partition("::")
            return bool(name) and self._symbols.symbol_defined(
                self.root, rel, name, nested=False
            )
        if kind == "test":
            # pytest node id: file::test_func or file::TestClass::test_method
            parts = [p for p in val.split("::") if p]
            if len(parts) < 2:
                return False
            rel, segs = parts[0], parts[1:]
            name = segs[-1] if len(segs) == 1 else f"{segs[-2]}.{segs[-1]}"
            return self._symbols.symbol_defined(self.root, rel, name, nested=True)
        if kind == "route":
            verb, _, path = val.strip().partition(" ")
            return (verb.upper(), self._routes.norm_route(path.strip())) in (
                self._route_set
            )
        return False

    @functools.cached_property
    def _touched_files(self) -> frozenset[str]:
        return gitio.touched_files(self.root, self.cfg.base_branch)

    @staticmethod
    def _has_gwt(text: str) -> bool:
        """The `## Acceptance Criteria` section mentions given/when/then (case-
        and bold-insensitive; no pair-matching)."""
        m = re.search(
            r"^##\s+Acceptance Criteria\s*$(.*?)(^##\s|\Z)", text, re.M | re.S | re.I
        )
        body = (m.group(1) if m else text).lower()
        return all(tok in body for tok in ("given", "when", "then"))

    def anchor_issues(self) -> tuple[list[str], list[str]]:
        """Gate 3 — spec grounding. Returns (hard, advisory) for in-scope story
        files (epic >= anchor_min_epic). Anchors are a tripwire for *absence*,
        never proof of done."""
        hard: list[str] = []
        advise: list[str] = []
        touched = self._touched_files
        for f in sorted(self.cfg.stories_path.glob("*.md")):
            head = f.name.split("-", 1)[0]
            if not head.isdigit() or int(head) < self.cfg.anchor_min_epic:
                continue
            text = f.read_text(encoding="utf-8", errors="replace")
            fm = parse_frontmatter_full(text)
            if not fm:
                continue  # malformed frontmatter is Gate 1's job
            status = fm.get("status")
            name = f.name
            if not self._has_gwt(text):
                advise.append(f"{name}: Acceptance Criteria missing given/when/then")
            if "anchor" not in fm:
                hard.append(
                    f"{name}: in-scope story has no `anchor:` field (list >=1 "
                    "symbol/test/route, or `anchor: none # reason`)"
                )
                continue
            anchor = fm["anchor"]
            if anchor is None or anchor == "none":
                if not re.search(r"^anchor:\s*none\s*#\s*\S", text, re.M):
                    advise.append(f"{name}: `anchor: none` should state a `# reason`")
                continue
            if not isinstance(anchor, list):
                hard.append(f"{name}: `anchor:` must be a list of entries or `none`")
                continue
            checked: list[tuple[str, bool]] = []
            files: set[str] = set()
            for entry in anchor:
                if not isinstance(entry, dict) or len(entry) != 1:
                    hard.append(f"{name}: malformed anchor entry {entry!r}")
                    continue
                kind, val = next(iter(entry.items()))
                if kind not in ("symbol", "test", "route"):
                    hard.append(f"{name}: unknown anchor kind {kind!r}")
                    continue
                checked.append((f"{kind}:{val}", self._anchor_present(kind, str(val))))
                if kind in ("symbol", "test"):
                    files.add(str(val).split("::", 1)[0])
            present = any(ok for _, ok in checked)
            # Direction 1 — a done story is grounded only if EVERY declared anchor
            # resolves (the anchor list is its definition of done).
            grounded = bool(checked) and all(ok for _, ok in checked)
            missing = [v for v, ok in checked if not ok]
            # "Looks started" keys on the TEST anchor when the story has one.
            test_results = [ok for label, ok in checked if label.startswith("test:")]
            started = any(test_results) if test_results else present
            if status in ("completed", "needs-refactoring") and not grounded:
                hard.append(
                    f"{name}: status {status!r} but {len(missing)}/{len(checked)} "
                    f"anchor(s) don't resolve: {missing}"
                )
            elif status == "in-progress" and not present:
                advise.append(f"{name}: in-progress, no anchor resolves yet")
            elif status in ("pending", "ready-for-dev") and (started or files & touched):
                why = (
                    "its invariant test resolves"
                    if any(test_results)
                    else "an anchor resolves"
                    if started
                    else "an anchor's file changed in-branch"
                )
                advise.append(
                    f"{name}: {status!r} but {why} — work looks started; "
                    "bump to in-progress?"
                )
        return hard, advise

    # -- Register model: generic clause-register engine ---------------------------

    @functools.cache
    def _register_text(self, path: Path) -> str:
        return path.read_text(encoding="utf-8", errors="replace")

    @functools.cache
    def _register_body(self, path: Path) -> str:
        """Register text with its frontmatter stripped. All register *content* is
        parsed from here so the `register:` block can never be misread as content."""
        return strip_frontmatter(self._register_text(path))

    @functools.cached_property
    def _register_specs(self) -> tuple[RegisterSpec, ...]:
        """Discover every clause register: a `type: register` doc carrying a
        `register:` block with `clause-prefixes`."""
        specs: list[RegisterSpec] = []
        for path in self.docs:
            fm = parse_frontmatter_full(self._register_text(path))
            if not fm or fm.get("type") != "register":
                continue
            block = fm.get("register")
            if not isinstance(block, dict):
                continue
            clause_prefixes = [str(p) for p in (block.get("clause-prefixes") or [])]
            if not clause_prefixes:
                continue
            crosscut = [str(p) for p in (block.get("crosscutting-prefixes") or [])]
            owner = block.get("owner-map") or {}
            owner_line = owner.get("line")
            specs.append(
                RegisterSpec(
                    name=str(block.get("name") or path.stem),
                    path=path,
                    clause_prefixes=tuple(clause_prefixes),
                    crosscut_prefixes=tuple(crosscut),
                    clause_re=_prefix_re(clause_prefixes),
                    crosscut_re=_prefix_re(crosscut) if crosscut else None,
                    enactable_glyphs=tuple(
                        str(g) for g in (block.get("enactable-glyphs") or [])
                    ),
                    proposed=frozenset(str(p) for p in (block.get("proposed") or [])),
                    owner_heading=(
                        str(owner["heading"]) if owner.get("heading") else None
                    ),
                    owner_until=str(owner["until"]) if owner.get("until") else None,
                    owner_line=re.compile(str(owner_line)) if owner_line else None,
                )
            )
        return tuple(specs)

    @functools.cached_property
    def _defined_adr_numbers(self) -> frozenset[int]:
        nums: set[int] = set()
        for f in self.cfg.adr_path.glob("[0-9]*.md"):
            m = re.match(r"(\d+)-", f.name)
            if m:
                nums.add(int(m.group(1)))
        return frozenset(nums)

    def _defined_ids(self, spec: RegisterSpec) -> frozenset[str]:
        """Clause ids the register defines (any occurrence of an owned-family id
        in the BODY — not the `register:` block)."""
        return frozenset(spec.clause_re.findall(self._register_body(spec.path)))

    def _crosscut_ids(self, spec: RegisterSpec) -> frozenset[str]:
        if spec.crosscut_re is None:
            return frozenset()
        return frozenset(spec.crosscut_re.findall(self._register_body(spec.path)))

    def registry_citation_issues(self) -> list[str]:
        """Every `ADR-NNNN` / clause / NFR id cited in a governed doc must resolve
        to its registry."""
        adr = self._defined_adr_numbers
        specs = self._register_specs
        defined = {s.path: self._defined_ids(s) for s in specs}
        crosscut = {s.path: self._crosscut_ids(s) for s in specs}
        adr_rel = self.cfg.adr_dir.rstrip("/")
        issues: list[str] = []
        for path in self.docs:
            text = self._register_text(path)
            fm = parse_frontmatter(text)
            if fm and fm.get("status") in ("archived", "temporary"):
                continue
            rel = self._rel(path)
            for num in {int(n) for n in _ADR_CITE.findall(text)}:
                if num not in adr:
                    issues.append(
                        f"{rel}: cites ADR-{num} — no {adr_rel}/{num:04d}-*.md"
                    )
            for spec in specs:
                for cid in set(spec.clause_re.findall(text)):
                    if cid not in defined[spec.path] and cid not in spec.proposed:
                        issues.append(
                            f"{rel}: cites {cid} — not defined in the "
                            f"{spec.name} register"
                        )
                if spec.crosscut_re is not None:
                    for nid in set(spec.crosscut_re.findall(text)):
                        if nid not in crosscut[spec.path]:
                            issues.append(
                                f"{rel}: cites {nid} — undefined in "
                                f"{spec.name} register"
                            )
        return sorted(issues)

    def _clause_glyphs(self, spec: RegisterSpec) -> dict[str, str]:
        """Map each register-defined clause id -> the glyph run on its definition
        line (`- **<ID>** <glyphs> — …`)."""
        rx = re.compile(rf"^- \*\*({spec.clause_re.pattern})\*\*\s*([^\n—-]*)", re.M)
        return {
            m.group(1): m.group(2) for m in rx.finditer(self._register_body(spec.path))
        }

    def registry_reverse_bijection_issues(
        self, specs: tuple[RegisterSpec, ...] | None = None
    ) -> list[str]:
        """Orphan check, per clause register that declares enactable glyphs: every
        *enactable* clause must be cited by >=1 governed doc outside its own
        register."""
        specs = self._register_specs if specs is None else specs
        issues: list[str] = []
        for spec in specs:
            if not spec.enactable_glyphs:
                continue
            glyphs = self._clause_glyphs(spec)
            cited: set[str] = set()
            for path in self.docs:
                if path == spec.path:
                    continue
                text = self._register_text(path)
                fm = parse_frontmatter(text)
                if fm and fm.get("status") in ("archived", "temporary"):
                    continue
                cited.update(spec.clause_re.findall(text))
            for cid, g in sorted(glyphs.items()):
                enactable = any(sym in g for sym in spec.enactable_glyphs)
                if not enactable or cid in spec.proposed:
                    continue
                if cid not in cited:
                    issues.append(
                        f"{cid}: enactable clause cited by no governed doc (orphan)"
                    )
        return issues

    def _clause_ownership(self, spec: RegisterSpec) -> dict[str, int]:
        """clause id -> owning epic, parsed from the register's declared owner-map
        section."""
        if spec.owner_heading is None or spec.owner_line is None:
            return {}
        text = self._register_body(spec.path)
        parts = text.split(spec.owner_heading)
        if len(parts) < 2:
            return {}
        section = parts[1].split(spec.owner_until)[0] if spec.owner_until else parts[1]
        owned: dict[str, int] = {}
        for line in section.splitlines():
            m = spec.owner_line.match(line)
            if m:
                for cid in spec.clause_re.findall(line):
                    owned.setdefault(cid, int(m.group(1)))
        return owned

    def coverage_completion_issues(
        self, specs: tuple[RegisterSpec, ...] | None = None
    ) -> list[str]:
        """Completion-gated coverage, per register that declares BOTH an enactable
        glyph legend and an owner-map."""
        specs = self._register_specs if specs is None else specs
        issues: list[str] = []
        for spec in specs:
            glyphs = self._clause_glyphs(spec)
            enactable = {
                c
                for c, g in glyphs.items()
                if any(x in g for x in spec.enactable_glyphs)
            }
            owned = self._clause_ownership(spec)
            if not enactable or not owned:
                continue

            by_epic: dict[int, list[tuple[str | None, set[str]]]] = {}
            satisfied: set[str] = set()  # cited by a completed OR deferred story
            for f in self.cfg.stories_path.glob("*.md"):
                head = f.name.split("-", 1)[0]
                if not head.isdigit():
                    continue
                text = f.read_text(encoding="utf-8", errors="replace")
                status = (parse_frontmatter(text) or {}).get("status")
                cites = set(spec.clause_re.findall(text))
                by_epic.setdefault(int(head), []).append((status, cites))
                if status in _WRAPPED:
                    satisfied |= cites

            for ep in sorted({e for c, e in owned.items() if c in enactable}):
                stories = by_epic.get(ep, [])
                if not stories or not all(s in _WRAPPED for s, _ in stories):
                    continue  # epic still has WIP -> dormant
                for cid in sorted(
                    c for c, e in owned.items() if e == ep and c in enactable
                ):
                    if cid not in satisfied:
                        issues.append(
                            f"epic {ep} is wrapped up but owns {cid}, which no "
                            "completed/deferred story cites — requirement "
                            "unaccounted for"
                        )
        return issues

    # -- Advisories ---------------------------------------------------------------

    def source_docs_issues(self) -> list[str]:
        """ADVISORY-ONLY dangle check for epic `source_docs:`. Schemes: `local`
        (this repo), one per configured sibling checkout, `url` (never checked).
        A sibling scheme is skipped entirely when that checkout is absent, so CI
        without it stays green. NEVER a hard gate — advice only."""
        issues: list[str] = []
        allowed = self.cfg.source_docs_schemes
        present = {
            scheme: self.cfg.sibling_path(scheme).is_dir()
            for scheme in self.cfg.siblings
        }
        for doc in sorted(self.cfg.epics_path.glob("epic-*.md")):
            text = doc.read_text(encoding="utf-8", errors="replace")
            rel = doc.relative_to(self.root)
            fm = parse_frontmatter_full(text) or {}
            entries = fm.get("source_docs") or []
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if isinstance(entry, str):  # bare path == implicit local
                    scheme, path = "local", entry.strip()
                elif isinstance(entry, dict) and len(entry) == 1:
                    ((scheme, path),) = entry.items()
                    scheme, path = str(scheme).strip(), str(path).strip()
                else:
                    issues.append(
                        f"{rel}: source_docs entry not a scheme:path — {entry!r}"
                    )
                    continue
                if scheme == "url":
                    continue
                if scheme == "local":
                    if path and not (self.root / path).exists():
                        issues.append(f"{rel}: source_docs local: {path} — not found")
                elif scheme in self.cfg.siblings:
                    missing = path and not (
                        self.cfg.sibling_path(scheme) / path
                    ).exists()
                    if present[scheme] and missing:
                        issues.append(
                            f"{rel}: source_docs {scheme}: {path} — "
                            f"not found in {self.cfg.siblings[scheme]}"
                        )
                else:
                    issues.append(
                        f"{rel}: source_docs unknown scheme {scheme!r} "
                        f"(allowed: {allowed})"
                    )
        return issues

    def register_thinness_issues(self) -> list[str]:
        """ADVISORY-ONLY: a register is a citeable INDEX, not a place to restate
        contract shapes, enum values, or version-specific ratification status."""
        issues: list[str] = []
        for spec in self._register_specs:
            text = self._register_text(spec.path)
            body = strip_frontmatter(text)
            offset = text[: len(text) - len(body)].count("\n")
            in_fence = False
            for i, line in enumerate(body.splitlines(), start=offset + 1):
                if line.lstrip().startswith("```"):
                    in_fence = not in_fence
                    issues.append(
                        f"{spec.name}:{i} — fenced code block (restated shape?)"
                    )
                    continue
                if in_fence:
                    continue
                if m := _REG_VER.search(line):
                    issues.append(
                        f"{spec.name}:{i} — version token {m.group(0)!r}; "
                        "ratification/version belongs in the contract changelog / ADRs"
                    )
                if m := _REG_BRACE.search(line):
                    issues.append(
                        f"{spec.name}:{i} — inline restated shape/enum {m.group(0)!r}; "
                        "shapes live in protocol-contract.md — cite the section by ID"
                    )
        return issues

    def unowned_clause_family_issues(self) -> list[str]:
        """ADVISORY-ONLY: clause-shaped citations whose FAMILY prefix NO
        discovered register claims — silently unchecked otherwise."""
        specs = self._register_specs
        owned = {p for s in specs for p in (*s.clause_prefixes, *s.crosscut_prefixes)}
        register_paths = {s.path for s in specs}
        by_family: dict[str, set[str]] = {}
        for path in self.docs:
            if path in register_paths:
                continue  # a register's own definitions aren't "citations"
            text = self._register_text(path)
            fm = parse_frontmatter(text)
            if fm and fm.get("status") in ("archived", "temporary"):
                continue
            rel = self._rel(path)
            for fam in (*_CLAUSE_FAMILY.findall(text), *_NFR_FAMILY.findall(text)):
                if fam not in owned:
                    by_family.setdefault(fam, set()).add(rel)
        return [
            f"{fam}: cited in {len(citers)} doc(s) but no register owns "
            f"the {fam} family"
            for fam, citers in sorted(by_family.items())
        ]
