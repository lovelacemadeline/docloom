"""Anchor-resolver plugin seam.

Gate 3 anchors come in three kinds — `symbol`, `test`, `route` — and each kind's
"does it exist?" question is *language/framework specific*. v1 ships:

  * symbol/test resolver ``python`` — stdlib-`ast` walk (no imports, no pytest run);
  * route resolver ``litestar``    — composes ``Controller.path`` + method decorators.

Adding a language is registering a new resolver here (or via a future entry-point
mechanism) — the engine never hardcodes one. Unimplemented names resolve to a
stub that fails loudly with a "not implemented yet" message rather than silently
passing or failing anchors.
"""

from __future__ import annotations

from typing import Protocol

from . import litestar_routes, python_symbols


class SymbolResolver(Protocol):
    def symbol_defined(self, root, relpath: str, name: str, *, nested: bool) -> bool: ...


class RouteResolver(Protocol):
    def route_set(self, root, globs: tuple[str, ...]) -> frozenset[tuple[str, str]]: ...

    def norm_route(self, path: str) -> str: ...


class _StubResolver:
    def __init__(self, name: str) -> None:
        self.name = name

    def _fail(self) -> None:
        raise NotImplementedError(
            f"anchor resolver {self.name!r} is declared in config but not "
            "implemented yet — v1 ships 'python' (symbol/test) and 'litestar' "
            "(route). Contributions: subclass the resolver Protocols in "
            "docloom.resolvers and register the name below."
        )

    def symbol_defined(self, root, relpath, name, *, nested):  # noqa: ANN001
        self._fail()

    def route_set(self, root, globs):  # noqa: ANN001
        self._fail()

    def norm_route(self, path):  # noqa: ANN001
        self._fail()


_SYMBOL_RESOLVERS: dict[str, object] = {"python": python_symbols}
_ROUTE_RESOLVERS: dict[str, object] = {"litestar": litestar_routes}
# Known-but-unimplemented names get an explicit stub so a typo'd/premature
# config fails with intent, not an obscure KeyError.
for _name in ("csharp", "typescript", "go", "rust"):
    _SYMBOL_RESOLVERS.setdefault(_name, _StubResolver(_name))
for _name in ("fastapi", "flask", "express", "aspnet"):
    _ROUTE_RESOLVERS.setdefault(_name, _StubResolver(_name))


def get_symbol_resolver(name: str):
    try:
        return _SYMBOL_RESOLVERS[name]
    except KeyError:
        raise SystemExit(f"docloom: unknown symbol resolver {name!r}") from None


def get_route_resolver(name: str):
    try:
        return _ROUTE_RESOLVERS[name]
    except KeyError:
        raise SystemExit(f"docloom: unknown route resolver {name!r}") from None
