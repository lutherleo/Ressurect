# Jev Resume Builder: Design Plan

## Context

Regenerating a resume with an LLM for every application causes style drift and silently drops or invents content. This tool keeps one canonical JSON of all resume components as the source of truth. **Jev** (TypeSafe's System One model) only *selects* from pre-written components, and deterministic code assembles and renders the result. Wording changes happen afterwards in a separate, manual Claude Code pass, and a validator checks that pass. Every resume is reproducible from `corpus.json` + JD + Jev response + overrides.

Owner profile: early career, targeting **developer, networking, and cybersecurity** roles in **NY or SF**. Corpus is roughly 4 experiences (2 internships, research lab lead, startup job), several projects, and one skills list per track.

Decisions made: **Python** CLI, **LaTeX → PDF** first (renderer pluggable for DOCX later), Claude polish is **manual in Claude Code** (the pipeline stops at JSON, then renders).

## Pipeline

```
corpus.json + jd.txt
   → build_questions   (state text + Jev question map)
   → jev_client        (one HTTP call, response cached to disk)
   → select            (deterministic: thresholds, top-N, overrides, ordering)
   → selected.json     ──(optional manual Claude Code polish)──→ polished.json
   → check             (validates polished vs selected: no new claims)
   → render            (Jinja2 → resume.tex → tectonic → resume.pdf)
```

## Repo layout

```
resume-jev/
  pyproject.toml            # typer, pydantic, httpx, jinja2, pyyaml, rich, pytest
  config.yaml               # tunables (below)
  data/corpus.json          # source of truth (user-maintained)
  templates/resume.tex.j2   # single-column, ATS-safe
  POLISH.md                 # rules for the manual Claude Code polish pass
  applications/<slug>/      # one folder per application (see Artifacts)
  src/resume_jev/
    cli.py  models.py  questions.py  jev_client.py
    select.py  overrides.py  check.py  render.py  latex.py
  tests/  (fixtures/ with sample corpus + canned Jev responses)
```

## Data model (`models.py`, pydantic; `data/corpus.json`)

```jsonc
{
  "profile": {
    "name": "...", "email": "...", "github": "...", "linkedin": "...",
    "locations": { "ny": "New York, NY", "sf": "San Francisco, CA" }
  },
  "experiences": [{
    "id": "exp_startup", "org": "...", "role": "...", "location": "...",
    "start": "2024-06", "end": "2025-01",            // "present" allowed
    "summary": "one-line plain description used in Jev state",
    "bullets": [{ "id": "exp_startup.b1", "text": "..." }]
  }],
  "projects": [{
    "id": "proj_netmon", "name": "...", "tech": ["..."], "link": "...",
    "summary": "...", "bullets": [{ "id": "proj_netmon.b1", "text": "..." }]
  }],
  "skill_lists": {                 // pre-curated, one per track
    "developer": { "Languages": ["..."], "Frameworks": ["..."] },
    "networking": { ... },
    "cybersecurity": { ... }
  },
  "education": [{ "school": "...", "degree": "...", "dates": "...", "details": ["..."] }],
  "certifications": ["..."]
}
```
IDs must be unique and stable. Validate on load (duplicate IDs and missing fields are errors).

## Jev request (`questions.py`, `jev_client.py`)

**State** (one user message): the JD text, then a delimited listing of every experience, bullet, and project with its ID and text, e.g. `[exp_startup] Software Engineer @ X — summary` followed by `[exp_startup.b1] bullet text`.

**Questions** (all in one request):

| id | type | purpose |
|---|---|---|
| `role_track` | choice | criteria: `developer` / `networking` / `cybersecurity`, each with a one-line description |
| `location` | choice | `ny` / `sf`, chosen from where the JD says the job is |
| `exp_<id>` | score | relevance of each experience to the JD |
| `proj_<id>` | score | relevance of each project to the JD |
| `bullet_<id>` | score | relevance of each bullet (used to trim bullets inside chosen roles/projects) |

Shared 0–5 relevance rubric (`criteria` list) for all score questions:
0 unrelated · 1 tangential/transferable soft skill only · 2 same broad field, different stack · 3 matches a nice-to-have · 4 directly matches a must-have · 5 matches multiple must-haves with concrete evidence.
Instructions say to weight must-have requirements most and to judge the work described, not keywords.

**API shape** (verify against TypeSafe's official docs at build time): `POST https://api.typesafe.ai/v1/systemone`, model `jev-latest`, `messages:[{role:"user", content: state}]`, `response_format: {type:"questions", questions:{...}}`, API key from env `TYPESAFE_API_KEY`. Response per question: choice → `choice, confidence, probabilities`; score → `score, confidence, probabilities, legend`. Also check whether a request has a maximum number of questions. If it does, `jev_client` sends the questions in chunks that share the same state and merges the results.

**Caching:** key = sha256(corpus + JD + questions + model). The raw request and response are stored in the application folder. Re-running selection after changing overrides never calls Jev again.

## Selection logic (`select.py`, pure functions, no I/O)

Rank by **expected score** = Σ level × p (from `probabilities`), not the argmax integer. This gives finer ordering.

1. **Track:** take the argmax of `role_track`. If the top two are within `track_merge_margin` (0.20), merge their skill lists (union per category, dedupe, cap at `skills_cap_per_category`) and flag the result as a hybrid.
2. **Location:** argmax of `location`. If confidence is below 0.6, use `default_location`.
3. **Experiences:** apply overrides, then take the top 2. Add the 3rd only if its expected score ≥ `third_exp_threshold` (3.0). Banned items are never included and pinned items always are (pins can push the count past 3, with a warning). **Render the chosen set reverse-chronologically**, not by score.
4. **Bullets:** within each chosen experience/project, keep the top `bullets_per_exp` / `bullets_per_proj`, shown in the corpus's original order.
5. **Projects:** top `top_projects` (3) after overrides.
6. Output `selected.json`: the same shape as the corpus, containing only the chosen items, plus a `_meta` block (track probabilities, hybrid flag, every item's expected score, overrides applied).

## Overrides (`overrides.py`, `applications/<slug>/overrides.yaml`)

```yaml
pin:   [exp_research_lab]
ban:   [proj_todo_app]
nudge: { proj_netmon: +1.0, exp_internship_a: -0.5 }   # added to expected score
force_track: null        # or developer|networking|cybersecurity
force_location: null
```
Overrides are stored per application, never in `corpus.json`. Each is applied after Jev scoring and before ranking.

## Manual polish + validation (`POLISH.md`, `check.py`)

`POLISH.md` holds the rules for Claude Code: copy `selected.json` to `polished.json` and only rephrase bullet text to mirror JD terminology. Never add technologies, tools, metrics, titles, or responsibilities that aren't already in the corpus. Keep every ID and number.

`resume check <slug>` compares `polished.json` against `selected.json`:
- **Error:** IDs added, removed, or reordered; structure changed; any number/metric changed or added.
- **Warning:** a tech-like token (capitalized term, or a term in the skills vocabulary) appears that doesn't occur anywhere in the corpus. These are possible invented claims, and each one is listed for the user to review.
- **Info:** a per-bullet diff.

`render` uses `polished.json` only if `check` passes with no errors. Otherwise it falls back to `selected.json` and warns.

## Rendering (`render.py`, `latex.py`, `templates/resume.tex.j2`)

- Jinja2 with LaTeX-safe delimiters (`\VAR{}`, `\BLOCK{}`) and an escape filter for `& % $ # _ { } ~ ^ \`.
- ATS-safe template: single column, standard section headings (Experience, Projects, Skills, Education), no tables, icons, or multi-column layouts, real text (not images).
- Compile with `tectonic` (one binary, fetches packages itself). Print a clear error if tectonic is missing.
- Renderer interface `render(selected, out_dir) -> Path` so a DOCX renderer can be added later.
- Warn if the PDF is longer than 1 page (count pages from the tectonic output or with pypdf).

## CLI (`cli.py`, typer)

```
resume validate-corpus                      # schema + ID checks
resume select <jd.txt> --name <slug>        # create app folder, call Jev (cached), write selected.json, print score table
resume reselect <slug>                      # re-run selection with current overrides, no Jev call
resume show <slug>                          # rich table: track probs, every item's expected score, chosen/pinned/banned
resume check <slug>                         # validate polished.json
resume render <slug>                        # → resume.tex + resume.pdf
resume run <jd.txt> --name <slug>           # select + render in one go (no polish)
```

## Config (`config.yaml`)

```yaml
jev: { endpoint: https://api.typesafe.ai/v1/systemone, model: jev-latest, timeout_s: 30 }
top_projects: 3
min_experiences: 2
max_experiences: 3
third_exp_threshold: 3.0
bullets_per_exp: 3
bullets_per_proj: 2
track_merge_margin: 0.20
skills_cap_per_category: 8
default_location: sf
```

## Artifacts per application (`applications/<slug>/`)

`jd.txt`, `jev_request.json`, `jev_response.json`, `overrides.yaml`, `selected.json`, `polished.json` (optional), `check_report.txt`, `resume.tex`, `resume.pdf`.

## Build order

1. `models.py` + sample `tests/fixtures/corpus.json` + `validate-corpus`.
2. `questions.py` (state builder + question map). Snapshot-test the generated request.
3. `select.py` + `overrides.py`, fully unit-tested against canned Jev responses.
4. `latex.py` / `render.py` + template. Render the fixture to PDF.
5. `jev_client.py` with caching and a `--mock` mode that reads a fixture response.
6. `check.py` + `POLISH.md`.
7. Wire up the CLI, then do a real-key end-to-end run.

## Verification

- **Unit tests (pytest):** expected-score math. Third experience included only at ≥ 3.0. Pin/ban/nudge precedence. Track merge when the margin is ≤ 0.20. Location fallback. Experiences ordered by date, not score. Bullet trimming keeps corpus order. LaTeX escaping of special characters.
- **check tests:** a changed number → error. A dropped ID → error. An unseen "Kubernetes" → warning. A pure rephrase → passes.
- **Render smoke test:** the fixture corpus compiles to a 1-page PDF via tectonic. Then run `pdftotext` and confirm the section headings and bullets come out as plain, ordered text (an ATS sanity check).
- **End-to-end with real key:** run `resume run` on three real JDs (one dev, one networking, one cyber). Check that `role_track` matches each, the skills list switches, and the top-3 projects make sense. Re-run `reselect` after adding a pin and confirm no new Jev call is made (cache hit) and the PDF changes as expected.
