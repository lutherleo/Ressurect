# Ressurect — Jev Resume Builder

Build job-targeted resumes without LLM style-drift. One canonical `corpus.json`
is the source of truth. The **Jev** model (TypeSafe System One) only *scores* how
relevant each experience, project, and bullet is to a job description;
deterministic code ranks, trims, orders, and renders the result to LaTeX → PDF.
See [`DESIGN.md`](DESIGN.md) for the full design.

## Install

```bash
uv run resume --help           # creates the venv and installs on first run
```

PDF rendering needs [`tectonic`](https://tectonic-typesetting.github.io/)
(`scoop install tectonic` / `winget install tectonic`). Without it, everything
works up to `resume.tex`.

## Quickstart (no API key needed)

```bash
# 1. Validate the corpus
uv run resume validate-corpus --corpus tests/fixtures/corpus.json

# 2. Select + render against a canned Jev response (mock mode)
uv run resume run path/to/jd.txt --name acme-backend \
    --corpus tests/fixtures/corpus.json \
    --mock tests/fixtures/jev_response.json
```

## Real runs

Set your key, then drop `--mock`:

```bash
export TYPESAFE_API_KEY=sk-...     # PowerShell: $env:TYPESAFE_API_KEY="sk-..."
uv run resume select path/to/jd.txt --name acme-backend
uv run resume show acme-backend                 # inspect the score table
# optionally hand-polish applications/acme-backend/selected.json -> polished.json
uv run resume check acme-backend                # guard the polish (see POLISH.md)
uv run resume render acme-backend               # -> resume.tex + resume.pdf
```

Overrides live in `applications/<slug>/overrides.yaml` (`pin` / `ban` / `nudge` /
`force_track` / `force_location`). After editing them:

```bash
uv run resume reselect acme-backend             # re-ranks; never calls Jev again
```

## Layout

- `data/corpus.json` — your resume components (edit this; a template ships here).
- `config.yaml` — selection tunables.
- `templates/resume.tex.j2` — the ATS-safe single-column template.
- `src/resume_jev/` — the package.
- `applications/<slug>/` — one folder per job (git-ignored; holds the Jev
  request/response cache, `selected.json`, `resume.tex`, etc.).

## Test

```bash
uv run --extra dev pytest
```
