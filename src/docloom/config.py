"""Configuration: everything the engine used to hardcode about one repo.

Resolution order for a project root:
  1. an explicit ``--config FILE``;
  2. ``docloom.toml`` at the root;
  3. ``[tool.docloom]`` in the root's ``pyproject.toml``;
  4. built-in defaults (which are a sane generic vocabulary — the same closed
     type/status enums the crosssense repo uses, with generic paths).

The vocabulary can alternatively be *self-describing*: set
``vocabulary.from-doc = "docs/doc-conventions.md"`` and declare a
``vocabulary:`` block in that doc's frontmatter — the human spec then IS the
machine spec, so the two can't drift.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path

from .frontmatter import parse_frontmatter_full


class ConfigError(Exception):
    """A configuration problem that must stop the run loudly (never a silent
    fallback to defaults — see `vocabulary.from-doc`)."""

DEFAULT_TYPES = frozenset(
    {
        "prd",
        "epic",
        "story",
        "register",
        "decision",
        "reference",
        "guide",
        "runbook",
        "plan",
        "research",
        "snapshot",
        "working-artifact",
    }
)
DEFAULT_STATUSES = frozenset(
    {
        "draft",
        "active",
        "superseded",
        "parked",
        "archived",
        "snapshot",
        "stub",
        "temporary",
    }
)
DEFAULT_CONDITIONAL = {"superseded": "superseded-by", "stub": "points-to"}
DEFAULT_EXECUTION_STATUSES = frozenset(
    {
        "pending",
        "ready-for-dev",
        "in-progress",
        "blocked",
        "needs-refactoring",
        "superseded",
        "completed",
        "deferred",
    }
)
DEFAULT_EXEMPTABLE_CHECKS = frozenset({"story-id", "bijection", "title"})


@dataclass(frozen=True)
class Config:
    """The full config surface. Field-per-field this is the union of every
    module-level constant the original checker carried."""

    root: Path = field(default_factory=Path.cwd)

    # -- corpus ---------------------------------------------------------------
    exclude_prefixes: tuple[str, ...] = (".claude/", "node_modules/")

    # -- canonical homes (relative to root) ------------------------------------
    tracker: str = "docs/sprint-status.yaml"
    stories_dir: str = "docs/stories"
    epics_dir: str = "docs/epics"
    adr_dir: str = "docs/adr"

    # -- vocabulary (closed enums) ---------------------------------------------
    types: frozenset[str] = DEFAULT_TYPES
    statuses: frozenset[str] = DEFAULT_STATUSES
    conditional: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_CONDITIONAL))
    execution_statuses: frozenset[str] = DEFAULT_EXECUTION_STATUSES
    exemptable_checks: frozenset[str] = DEFAULT_EXEMPTABLE_CHECKS

    # -- Gate 3 (spec-grounding anchors) ----------------------------------------
    anchor_min_epic: int = 1
    anchor_enforced: bool = True
    base_branch: str = "main"

    # -- anchor resolvers (pluggable; python/litestar ship in v1) ---------------
    symbol_resolver: str = "python"
    route_resolver: str = "litestar"
    route_globs: tuple[str, ...] = ("src/**/*.py",)

    # -- source_docs sibling schemes: scheme name -> path relative to root ------
    siblings: dict[str, str] = field(default_factory=dict)

    # -- self-describing vocabulary: the conventions doc that owns the enums ----
    # Set (via `vocabulary.from-doc`) when the doc's `vocabulary:` frontmatter
    # block is the authoritative vocabulary source. Enables the doc-internal
    # agreement check (prose tables must match the block).
    vocab_from_doc: str | None = None

    @property
    def tracker_path(self) -> Path:
        return self.root / self.tracker

    @property
    def stories_path(self) -> Path:
        return self.root / self.stories_dir

    @property
    def epics_path(self) -> Path:
        return self.root / self.epics_dir

    @property
    def adr_path(self) -> Path:
        return self.root / self.adr_dir

    def sibling_path(self, scheme: str) -> Path:
        return (self.root / self.siblings[scheme]).resolve()

    @property
    def source_docs_schemes(self) -> str:
        """The `(allowed: …)` display for source_docs messages, closed-set order:
        local, then each sibling scheme, then url."""
        return "/".join(["local", *self.siblings, "url"])


def _vocab_from_doc(root: Path, relpath: str) -> dict[str, object]:
    """Read the `vocabulary:` frontmatter block from the conventions doc itself
    (the self-describing default). FAIL LOUD, never fall back: once a repo says
    "the doc is the spec", a missing doc or a mangled block must stop the run —
    a silent revert to built-in defaults would swap the repo's intended
    vocabulary out from under it (previously-valid docs start failing, or
    previously-invalid ones pass, with nothing screaming)."""
    doc = root / relpath
    if not doc.exists():
        raise ConfigError(
            f"vocabulary.from-doc points at {relpath} — file not found"
        )
    fm = parse_frontmatter_full(doc.read_text(encoding="utf-8", errors="replace"))
    if fm is None:
        raise ConfigError(
            f"vocabulary.from-doc: {relpath} has no parseable frontmatter"
        )
    block = fm.get("vocabulary")
    if not isinstance(block, dict):
        raise ConfigError(
            f"vocabulary.from-doc: {relpath} declares no `vocabulary:` "
            "frontmatter block"
        )
    for required in ("types", "statuses"):
        if not isinstance(block.get(required), list) or not block[required]:
            raise ConfigError(
                f"vocabulary.from-doc: {relpath} `vocabulary:` block is missing "
                f"a non-empty `{required}:` list"
            )
    return block


def _apply(cfg: Config, data: dict[str, object]) -> Config:
    """Overlay one parsed `[docloom]`-shaped table onto a Config."""

    def strs(key: str) -> tuple[str, ...] | None:
        v = data.get(key)
        return tuple(str(x) for x in v) if isinstance(v, list) else None

    updates: dict[str, object] = {}
    if (v := strs("exclude")) is not None:
        updates["exclude_prefixes"] = v
    for key, attr in [
        ("tracker", "tracker"),
        ("stories-dir", "stories_dir"),
        ("epics-dir", "epics_dir"),
        ("adr-dir", "adr_dir"),
        ("base-branch", "base_branch"),
    ]:
        if key in data:
            updates[attr] = str(data[key])

    vocab = data.get("vocabulary")
    if isinstance(vocab, dict):
        if "from-doc" in vocab:
            updates["vocab_from_doc"] = str(vocab["from-doc"])
            vocab = {**_vocab_from_doc(cfg.root, str(vocab["from-doc"])), **vocab}
        if isinstance(vocab.get("types"), list):
            updates["types"] = frozenset(str(x) for x in vocab["types"])
        if isinstance(vocab.get("statuses"), list):
            updates["statuses"] = frozenset(str(x) for x in vocab["statuses"])
        if isinstance(vocab.get("execution-statuses"), list):
            updates["execution_statuses"] = frozenset(
                str(x) for x in vocab["execution-statuses"]
            )
        if isinstance(vocab.get("exemptable-checks"), list):
            updates["exemptable_checks"] = frozenset(
                str(x) for x in vocab["exemptable-checks"]
            )
        if isinstance(vocab.get("conditional"), dict):
            updates["conditional"] = {
                str(k): str(v) for k, v in vocab["conditional"].items()
            }

    gate3 = data.get("gate3")
    if isinstance(gate3, dict):
        if "min-epic" in gate3:
            updates["anchor_min_epic"] = int(gate3["min-epic"])  # type: ignore[arg-type]
        if "enforced" in gate3:
            updates["anchor_enforced"] = bool(gate3["enforced"])

    anchors = data.get("anchors")
    if isinstance(anchors, dict):
        if "resolver" in anchors:
            updates["symbol_resolver"] = str(anchors["resolver"])
        if "route-resolver" in anchors:
            updates["route_resolver"] = str(anchors["route-resolver"])
        if isinstance(anchors.get("route-globs"), list):
            updates["route_globs"] = tuple(str(x) for x in anchors["route-globs"])

    siblings = data.get("siblings")
    if isinstance(siblings, dict):
        updates["siblings"] = {str(k): str(v) for k, v in siblings.items()}

    return replace(cfg, **updates)  # type: ignore[arg-type]


def load_config(root: Path, config_file: Path | None = None) -> Config:
    cfg = Config(root=root.resolve())
    if config_file is not None:
        raw = tomllib.loads(config_file.read_text(encoding="utf-8"))
        return _apply(cfg, raw.get("docloom", raw))
    toml = root / "docloom.toml"
    if toml.exists():
        raw = tomllib.loads(toml.read_text(encoding="utf-8"))
        return _apply(cfg, raw.get("docloom", raw))
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        raw = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        tool = raw.get("tool", {}).get("docloom")
        if isinstance(tool, dict):
            return _apply(cfg, tool)
    return cfg
