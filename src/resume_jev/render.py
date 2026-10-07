"""Render a ``selected``/``polished`` dict to ``resume.tex`` and compile a PDF.

The renderer interface is ``render(selected, out_dir) -> Path`` so a DOCX
renderer can be slotted in later. ``render_tex`` is split out so the LaTeX path
can be verified without ``tectonic`` installed.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .latex import make_env

TEMPLATE_NAME = "resume.tex.j2"


class RenderError(RuntimeError):
    pass


def render_tex(
    selected: dict,
    out_dir: str | Path,
    template_dir: str | Path = "templates",
) -> Path:
    """Render the LaTeX source to ``<out_dir>/resume.tex`` and return its path."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    env = make_env(template_dir)
    template = env.get_template(TEMPLATE_NAME)
    tex = template.render(**{k: v for k, v in selected.items() if not k.startswith("_")})
    if not tex.endswith("\n"):
        tex += "\n"
    tex_path = out_dir / "resume.tex"
    tex_path.write_text(tex, encoding="utf-8")
    return tex_path


def _page_count(pdf_path: Path) -> int | None:
    """Best-effort page count via pdftotext form-feed separators."""
    pdftotext = shutil.which("pdftotext")
    if not pdftotext:
        return None
    try:
        proc = subprocess.run(
            [pdftotext, str(pdf_path), "-"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, OSError):
        return None
    return proc.stdout.count("\f") + 1


def compile_pdf(tex_path: str | Path) -> Path:
    """Compile a .tex file to PDF with tectonic. Raise RenderError if tectonic
    is missing or the compile fails."""
    tex_path = Path(tex_path)
    tectonic = shutil.which("tectonic")
    if not tectonic:
        raise RenderError(
            "tectonic is not installed. Install it (e.g. `scoop install tectonic`, "
            "`winget install tectonic`, or a prebuilt binary) to produce a PDF. "
            f"The LaTeX source was still written to {tex_path}."
        )
    try:
        subprocess.run(
            [tectonic, str(tex_path), "--outdir", str(tex_path.parent)],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise RenderError(f"tectonic failed:\n{exc.stderr or exc.stdout}") from exc
    pdf_path = tex_path.with_suffix(".pdf")
    if not pdf_path.exists():
        raise RenderError(f"tectonic reported success but {pdf_path} is missing")
    return pdf_path


def render(
    selected: dict,
    out_dir: str | Path,
    template_dir: str | Path = "templates",
) -> tuple[Path, list[str]]:
    """Render .tex then compile to PDF. Returns (pdf_path, warnings).

    Raises RenderError if tectonic is unavailable or the compile fails; the .tex
    is written regardless so callers can inspect it.
    """
    warnings: list[str] = []
    tex_path = render_tex(selected, out_dir, template_dir)
    pdf_path = compile_pdf(tex_path)
    pages = _page_count(pdf_path)
    if pages is not None and pages > 1:
        warnings.append(f"resume is {pages} pages; aim for 1 page")
    return pdf_path, warnings
