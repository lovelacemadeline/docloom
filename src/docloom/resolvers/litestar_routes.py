"""Litestar route anchor resolver — composes Controller.path + method decorators."""

from __future__ import annotations

import ast
import re
from pathlib import Path

_HTTP_DECOS = {"get", "post", "put", "patch", "delete"}


def norm_route(path: str) -> str:
    """Normalize a route path: collapse `{name:type}`/`{name}` params to `{}` and
    squeeze slashes, so an anchor matches the composed handler path structurally."""
    path = re.sub(r"\{[^}]*\}", "{}", path)
    path = re.sub(r"/{2,}", "/", path).rstrip("/")
    return path or "/"


def route_set(root: Path, globs: tuple[str, ...]) -> frozenset[tuple[str, str]]:
    """(VERB, normalized-path) for every litestar handler under the configured
    globs, composing a controller's class-level `path = "..."` with each method's
    `@get/@post(...)` decorator (module-level handlers use the decorator arg as
    the full path)."""
    routes: set[tuple[str, str]] = set()

    def add_handler(node: ast.stmt, prefix: str) -> None:
        for deco in getattr(node, "decorator_list", []):
            if not isinstance(deco, ast.Call):
                continue
            fn = deco.func
            verb = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
            if verb not in _HTTP_DECOS and verb != "websocket":
                continue
            arg = deco.args[0] if deco.args else None
            seg = arg.value if isinstance(arg, ast.Constant) else ""
            out = "WS" if verb == "websocket" else verb.upper()
            routes.add((out, norm_route(prefix + str(seg))))

    for glob in globs:
        for f in root.glob(glob):
            try:
                tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                continue
            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    cpath = ""
                    for sub in node.body:
                        if (
                            isinstance(sub, ast.Assign)
                            and any(
                                isinstance(t, ast.Name) and t.id == "path"
                                for t in sub.targets
                            )
                            and isinstance(sub.value, ast.Constant)
                        ):
                            cpath = str(sub.value.value)
                    for sub in node.body:
                        if isinstance(sub, ast.FunctionDef | ast.AsyncFunctionDef):
                            add_handler(sub, cpath)
                elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                    add_handler(node, "")
    return frozenset(routes)
