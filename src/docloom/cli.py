"""docloom CLI: `check` (the gauntlet) and `init` (bootstrap a project)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import ConfigError, load_config
from .engine import Gauntlet
from .report import run_check
from .scaffold import init_project


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="docloom",
        description="Documentation-conventions gauntlet: typed frontmatter, "
        "tracker bijection, citeable registers, spec-grounding anchors.",
    )
    sub = ap.add_subparsers(dest="cmd")

    chk = sub.add_parser("check", help="run the gauntlet (default command)")
    chk.add_argument("--root", type=Path, default=Path.cwd(), help="project root")
    chk.add_argument(
        "--config", type=Path, default=None, help="explicit docloom.toml path"
    )
    chk.add_argument("--summary", action="store_true", help="counts only")
    chk.add_argument(
        "--valid-if-present",
        action="store_true",
        help="only fail docs that declare a type: but get it wrong",
    )

    ctx = sub.add_parser(
        "context",
        help="tiered path manifest of every doc related to an epic/story",
    )
    ctx.add_argument("target", help="epic or story id: 26, epic-26, 26.1, 26-1")
    ctx.add_argument("--root", type=Path, default=Path.cwd(), help="project root")
    ctx.add_argument(
        "--config", type=Path, default=None, help="explicit docloom.toml path"
    )

    ini = sub.add_parser("init", help="scaffold conventions into a project")
    ini.add_argument("--root", type=Path, default=Path.cwd(), help="project root")
    ini.add_argument("--name", default=None, help="project name (default: dir name)")
    ini.add_argument(
        "--advisory",
        action="store_true",
        help="start with Gate 3 anchors advisory-only (brownfield ratchet)",
    )
    ini.add_argument(
        "--no-claude",
        action="store_true",
        help="skip the .claude/ skill + CLAUDE.md section",
    )

    args = ap.parse_args(argv)
    if args.cmd is None:
        args = ap.parse_args(["check", *(argv or sys.argv[1:])])

    if args.cmd == "check":
        try:
            cfg = load_config(args.root.resolve(), args.config)
        except ConfigError as exc:
            print(f"docloom: config error — {exc}", file=sys.stderr)
            return 2
        return run_check(
            Gauntlet(cfg),
            summary=args.summary,
            valid_if_present=args.valid_if_present,
        )
    if args.cmd == "context":
        from .context import run_context

        try:
            cfg = load_config(args.root.resolve(), args.config)
        except ConfigError as exc:
            print(f"docloom: config error — {exc}", file=sys.stderr)
            return 2
        return run_context(Gauntlet(cfg), args.target)
    if args.cmd == "init":
        return init_project(
            args.root.resolve(),
            name=args.name,
            advisory=args.advisory,
            claude=not args.no_claude,
        )
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
