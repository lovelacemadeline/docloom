"""Frontmatter parsing — a faithful port of the original checker's two parsers.

Both reject an *unterminated* block: docs use `---` as a body section rule, so a
missing closing fence would otherwise latch onto the first body `---` and parse
headings/prose as keys. A Markdown heading before the supposed close means the
real fence is missing -> treat as malformed (untyped), so the hard gate fires.
"""

from __future__ import annotations

import re

import yaml


def parse_frontmatter(text: str) -> dict[str, str] | None:
    """Return top-level scalar frontmatter keys, or None if no frontmatter.

    Deliberately minimal: captures unindented ``key: value`` lines (stripping
    inline ``# comments``), which covers type/status/superseded-by/points-to.
    Indented continuation lines (block scalars like ``purpose: >``) are ignored.
    """
    if not text.startswith("---"):
        return None
    lines = text.splitlines()
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return None
    if any(re.match(r"^#{1,6}\s", lines[i]) for i in range(1, end)):
        return None
    fm: dict[str, str] = {}
    for line in lines[1:end]:
        if not line or line[0] in " \t#":
            continue
        m = re.match(r"^([A-Za-z][\w-]*):\s*(.*)$", line)
        if m:
            value = re.sub(r"\s+#.*$", "", m.group(2)).strip()
            fm[m.group(1)] = value
    return fm


def parse_frontmatter_full(text: str) -> dict[str, object] | None:
    """Full YAML parse of the frontmatter block (handles list/nested values,
    unlike the deliberately-scalar `parse_frontmatter`). None if absent/malformed
    — including the unterminated-block case the scalar parser also rejects."""
    if not text.startswith("---"):
        return None
    lines = text.splitlines()
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return None
    if any(re.match(r"^#{1,6}\s", lines[i]) for i in range(1, end)):
        return None
    try:
        data = yaml.safe_load("\n".join(lines[1:end]))
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def strip_frontmatter(text: str) -> str:
    """Text with its frontmatter block removed (register *content* parsing)."""
    if text.startswith("---"):
        parts = text.split("\n---", 1)
        if len(parts) == 2:
            return parts[1]
    return text
