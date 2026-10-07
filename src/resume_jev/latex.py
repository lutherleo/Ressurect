"""LaTeX escaping and the Jinja2 environment (LaTeX-safe delimiters)."""

from __future__ import annotations

import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

# Order-independent: a single regex pass means no replacement re-escapes another.
_TEX_MAP = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}
_TEX_RE = re.compile("|".join(re.escape(c) for c in _TEX_MAP))


def tex_escape(value) -> str:
    """Escape LaTeX special characters: & % $ # _ { } ~ ^ \\."""
    if value is None:
        return ""
    return _TEX_RE.sub(lambda m: _TEX_MAP[m.group()], str(value))


def make_env(template_dir: str | Path) -> Environment:
    env = Environment(
        block_start_string=r"\BLOCK{",
        block_end_string="}",
        variable_start_string=r"\VAR{",
        variable_end_string="}",
        comment_start_string=r"\#{",
        comment_end_string="}",
        line_statement_prefix="%%",
        line_comment_prefix="%#",
        trim_blocks=True,
        lstrip_blocks=True,
        autoescape=False,
        loader=FileSystemLoader(str(template_dir)),
    )
    env.filters["tex"] = tex_escape
    return env
