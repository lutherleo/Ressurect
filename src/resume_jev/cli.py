"""`resume` command-line interface."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from . import check as check_mod
from . import jev_client, questions
from .config import load_config
from .models import CorpusError, load_corpus
from .overrides import load_overrides, validate_against_corpus
from .render import RenderError, compile_pdf, render_tex
from .select import select as run_select

app = typer.Typer(add_completion=False, help="Job-targeted resume builder (Jev selects, code renders).")
console = Console()

APPS_ROOT = Path("applications")
DEFAULT_CORPUS = Path("data/corpus.json")
DEFAULT_CONFIG = Path("config.yaml")
DEFAULT_TEMPLATES = Path("templates")

OVERRIDES_TEMPLATE = """\
# Per-application overrides. Applied after Jev scoring, before ranking.
pin: []        # ids always included (experiences / projects)
ban: []        # ids never included
nudge: {}      # id: delta added to expected score, e.g. {proj_netmon: 1.0}
force_track: null      # or one of your corpus tracks
force_location: null   # or one of your corpus location labels
"""


def _die(msg: str) -> None:
    console.print(f"[bold red]error:[/] {msg}")
    raise typer.Exit(code=1)


def _app_dir(slug: str) -> Path:
    return APPS_ROOT / slug


def _load_corpus_or_die(corpus_path: Path):
    try:
        return load_corpus(corpus_path)
    except CorpusError as exc:
        _die(str(exc))


def _ensure_overrides(app_dir: Path) -> Path:
    path = app_dir / "overrides.yaml"
    if not path.exists():
        app_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(OVERRIDES_TEMPLATE, encoding="utf-8")
    return path


def _score_table(corpus, selected: dict) -> Table:
    meta = selected["_meta"]
    scores = meta["scores"]
    chosen_ids = {e["id"] for e in selected["experiences"]} | {p["id"] for p in selected["projects"]}
    ov = meta["overrides_applied"]
    pinned, banned = set(ov.get("pin", [])), set(ov.get("ban", []))

    table = Table(title="Selection", show_lines=False)
    table.add_column("id")
    table.add_column("kind")
    table.add_column("exp. score", justify="right")
    table.add_column("status")

    def status(the_id: str) -> str:
        bits = []
        if the_id in chosen_ids:
            bits.append("[green]chosen[/]")
        if the_id in pinned:
            bits.append("[cyan]pinned[/]")
        if the_id in banned:
            bits.append("[red]banned[/]")
        return " ".join(bits) or "[dim]dropped[/]"

    for e in corpus.experiences:
        table.add_row(e.id, "experience", f"{scores.get(e.id, 0.0):.2f}", status(e.id))
    for p in corpus.projects:
        table.add_row(p.id, "project", f"{scores.get(p.id, 0.0):.2f}", status(p.id))
    return table


def _print_selection(corpus, selected: dict, warnings: list[str], from_cache: bool | None) -> None:
    meta = selected["_meta"]
    probs = ", ".join(f"{k}={v:.2f}" for k, v in meta["track_probabilities"].items())
    hybrid = " [yellow](hybrid)[/]" if meta["track_hybrid"] else ""
    console.print(f"[bold]track:[/] {meta['track']}{hybrid}   ({probs})")
    console.print(
        f"[bold]location:[/] {meta['location']} -> {meta['location_label']} "
        f"(confidence {meta['location_confidence']:.2f})"
    )
    if from_cache is not None:
        console.print(f"[dim]jev: {'cache hit (no API call)' if from_cache else 'fetched response'}[/]")
    console.print(_score_table(corpus, selected))
    for w in warnings:
        console.print(f"[yellow]warning:[/] {w}")


def _write_selected(app_dir: Path, selected: dict) -> None:
    (app_dir / "selected.json").write_text(
        json.dumps(selected, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# --- commands ------------------------------------------------------------------


@app.command("validate-corpus")
def validate_corpus(
    corpus: Path = typer.Option(DEFAULT_CORPUS, help="Path to corpus.json"),
):
    """Schema + unique-id checks on the corpus."""
    c = _load_corpus_or_die(corpus)
    console.print(
        f"[green]ok[/]: {len(c.experiences)} experiences, {len(c.projects)} projects, "
        f"tracks={c.tracks()}"
    )


@app.command()
def select(
    jd: Path = typer.Argument(..., help="Path to the job-description text file"),
    name: str = typer.Option(..., "--name", help="Application slug (folder under applications/)"),
    corpus: Path = typer.Option(DEFAULT_CORPUS, help="Path to corpus.json"),
    config: Path = typer.Option(DEFAULT_CONFIG, help="Path to config.yaml"),
    mock: Path | None = typer.Option(None, help="Use a canned Jev response file instead of the API"),
    refresh: bool = typer.Option(False, help="Force a new Jev call even if cached"),
):
    """Create the app folder, call Jev (cached), write selected.json."""
    if not jd.exists():
        _die(f"job description not found: {jd}")
    cfg = load_config(config)
    c = _load_corpus_or_die(corpus)
    jd_text = jd.read_text(encoding="utf-8")

    app_dir = _app_dir(name)
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "jd.txt").write_text(jd_text, encoding="utf-8")
    ov_path = _ensure_overrides(app_dir)

    request = questions.build_request(c, jd_text, cfg.jev.model)
    try:
        response, from_cache = jev_client.get_response(
            request,
            app_dir,
            endpoint=cfg.jev.endpoint,
            timeout=cfg.jev.timeout_s,
            mock_path=mock,
            refresh=refresh,
        )
    except jev_client.JevError as exc:
        _die(str(exc))

    ov = load_overrides(ov_path)
    for w in validate_against_corpus(ov, c):
        console.print(f"[yellow]warning:[/] {w}")
    result = run_select(c, jev_client.answers_of(response), ov, cfg)
    _write_selected(app_dir, result.selected)
    _print_selection(c, result.selected, result.warnings, from_cache)
    console.print(f"[dim]wrote {app_dir / 'selected.json'}[/]")


@app.command()
def reselect(
    name: str = typer.Argument(..., help="Application slug"),
    corpus: Path = typer.Option(DEFAULT_CORPUS, help="Path to corpus.json"),
    config: Path = typer.Option(DEFAULT_CONFIG, help="Path to config.yaml"),
):
    """Re-run selection with current overrides. Never calls Jev."""
    cfg = load_config(config)
    c = _load_corpus_or_die(corpus)
    app_dir = _app_dir(name)
    response = jev_client.load_cached_response(app_dir)
    if response is None:
        _die(f"no cached Jev response in {app_dir}; run `resume select` first")
    ov = load_overrides(app_dir / "overrides.yaml")
    for w in validate_against_corpus(ov, c):
        console.print(f"[yellow]warning:[/] {w}")
    result = run_select(c, jev_client.answers_of(response), ov, cfg)
    _write_selected(app_dir, result.selected)
    _print_selection(c, result.selected, result.warnings, from_cache=True)


@app.command()
def show(
    name: str = typer.Argument(..., help="Application slug"),
    corpus: Path = typer.Option(DEFAULT_CORPUS, help="Path to corpus.json"),
):
    """Show the selection table for an existing application."""
    c = _load_corpus_or_die(corpus)
    app_dir = _app_dir(name)
    sel_path = app_dir / "selected.json"
    if not sel_path.exists():
        _die(f"no selected.json in {app_dir}; run `resume select` first")
    selected = json.loads(sel_path.read_text(encoding="utf-8"))
    _print_selection(c, selected, warnings=[], from_cache=None)


@app.command()
def check(
    name: str = typer.Argument(..., help="Application slug"),
    corpus: Path = typer.Option(DEFAULT_CORPUS, help="Path to corpus.json"),
):
    """Validate polished.json against selected.json."""
    c = _load_corpus_or_die(corpus)
    app_dir = _app_dir(name)
    sel_path, pol_path = app_dir / "selected.json", app_dir / "polished.json"
    if not sel_path.exists():
        _die(f"no selected.json in {app_dir}")
    if not pol_path.exists():
        _die(f"no polished.json in {app_dir}; copy selected.json and rephrase (see POLISH.md)")
    selected = json.loads(sel_path.read_text(encoding="utf-8"))
    polished = json.loads(pol_path.read_text(encoding="utf-8"))
    report = check_mod.check(selected, polished, c)
    (app_dir / "check_report.txt").write_text(report.text(), encoding="utf-8")
    console.print(report.text())
    if not report.ok:
        raise typer.Exit(code=1)


@app.command()
def render(
    name: str = typer.Argument(..., help="Application slug"),
    corpus: Path = typer.Option(DEFAULT_CORPUS, help="Path to corpus.json"),
    templates: Path = typer.Option(DEFAULT_TEMPLATES, help="Template directory"),
):
    """Render resume.tex and compile resume.pdf.

    Uses polished.json if present and it passes `check`; otherwise selected.json.
    """
    c = _load_corpus_or_die(corpus)
    app_dir = _app_dir(name)
    pol_path = app_dir / "polished.json"
    sel_path = app_dir / "selected.json"
    # If a polished file exists, only use it when check passes.
    if pol_path.exists() and sel_path.exists():
        selected = json.loads(sel_path.read_text(encoding="utf-8"))
        polished = json.loads(pol_path.read_text(encoding="utf-8"))
        report = check_mod.check(selected, polished, c)
        if not report.ok:
            console.print("[yellow]polished.json failed check; rendering selected.json instead[/]")
            console.print(report.text())
            pol_path = pol_path.with_name("__skip_polished__")  # force fallback
    _do_render_with_fallback(app_dir, templates, use_polished=pol_path.exists())


def _do_render_with_fallback(app_dir: Path, template_dir: Path, use_polished: bool) -> None:
    sel_path, pol_path = app_dir / "selected.json", app_dir / "polished.json"
    if not sel_path.exists():
        _die(f"no selected.json in {app_dir}; run `resume select` first")
    if use_polished and pol_path.exists():
        source = json.loads(pol_path.read_text(encoding="utf-8"))
        which = "polished.json"
    else:
        source = json.loads(sel_path.read_text(encoding="utf-8"))
        which = "selected.json"
    tex_path = render_tex(source, app_dir, template_dir)
    console.print(f"[green]wrote[/] {tex_path} (from {which})")
    try:
        pdf_path = compile_pdf(tex_path)
    except RenderError as exc:
        console.print(f"[yellow]note:[/] {exc}")
        raise typer.Exit(code=1)
    console.print(f"[green]wrote[/] {pdf_path}")


@app.command()
def ui(
    corpus: Path = typer.Option(DEFAULT_CORPUS, help="Path to corpus.json"),
    config: Path = typer.Option(DEFAULT_CONFIG, help="Path to config.yaml"),
    host: str = typer.Option("127.0.0.1", help="Host to bind"),
    port: int = typer.Option(8000, help="Port to bind"),
):
    """Launch the local web UI to run selections and preview resumes."""
    import uvicorn

    from .webui import create_app

    application = create_app(str(corpus), str(config))
    console.print(f"[green]Jev Resume Builder UI[/] -> http://{host}:{port}  (corpus: {corpus})")
    console.print("[dim]Ctrl+C to stop.[/]")
    uvicorn.run(application, host=host, port=port, log_level="warning")


@app.command()
def run(
    jd: Path = typer.Argument(..., help="Path to the job-description text file"),
    name: str = typer.Option(..., "--name", help="Application slug"),
    corpus: Path = typer.Option(DEFAULT_CORPUS, help="Path to corpus.json"),
    config: Path = typer.Option(DEFAULT_CONFIG, help="Path to config.yaml"),
    templates: Path = typer.Option(DEFAULT_TEMPLATES, help="Template directory"),
    mock: Path | None = typer.Option(None, help="Use a canned Jev response file instead of the API"),
):
    """select + render in one go (no polish)."""
    select(jd=jd, name=name, corpus=corpus, config=config, mock=mock, refresh=False)
    _do_render_with_fallback(_app_dir(name), templates, use_polished=False)


if __name__ == "__main__":
    app()
