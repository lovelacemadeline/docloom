"""Python symbol/test anchor resolver — stdlib `ast`, no imports, no pytest run."""

from __future__ import annotations

import ast
from pathlib import Path


def _member_defined(body: list[ast.stmt], target: str) -> bool:
    """`target` is a def/class/assignment name directly in this statement body."""
    for n in body:
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            if n.name == target:
                return True
        elif isinstance(n, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == target for t in n.targets):
                return True
        elif isinstance(n, ast.AnnAssign):
            if isinstance(n.target, ast.Name) and n.target.id == target:
                return True
    return False


def symbol_defined(root: Path, relpath: str, name: str, *, nested: bool) -> bool:
    """True if `name` is defined in the Python file. Dotted `Class.member` looks
    inside that class; `nested` also matches a bare name defined in ANY class body
    (test functions often live in a `Test*` class)."""
    f = root / relpath
    if f.suffix != ".py" or not f.exists():
        return False
    try:
        tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return False
    if "." in name:
        cls, _, member = name.partition(".")
        return any(
            isinstance(n, ast.ClassDef)
            and n.name == cls
            and _member_defined(n.body, member)
            for n in tree.body
        )
    if _member_defined(tree.body, name):
        return True
    if nested:
        return any(
            isinstance(n, ast.ClassDef) and _member_defined(n.body, name)
            for n in tree.body
        )
    return False
