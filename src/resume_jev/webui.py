"""A small local web UI to run selections and inspect results in the browser.

Launched with ``resume ui``. Reuses the exact same pipeline as the CLI
(``questions`` -> ``jev_client`` -> ``select``), so what you see here is what the
renderer gets. The API key is read from ``TYPESAFE_API_KEY`` in the server's
environment, never from the page.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from . import jev_client, questions
from .config import load_config
from .models import Corpus, CorpusError, load_corpus
from .overrides import load_overrides, validate_against_corpus
from .select import select as run_select

DEFAULT_MOCK = "tests/fixtures/jev_response.json"


def build_catalog(corpus: Corpus) -> dict[str, dict]:
    catalog: dict[str, dict] = {}
    for e in corpus.experiences:
        catalog[e.id] = {"kind": "experience", "label": f"{e.role} @ {e.org}"}
    for p in corpus.projects:
        catalog[p.id] = {"kind": "project", "label": p.name}
    return catalog


class SelectBody(BaseModel):
    jd: str
    slug: str = "preview"
    mock: bool = False
    mock_path: str | None = None
    refresh: bool = True


EMPTY_CORPUS = {
    "profile": {"name": "", "email": "", "github": "", "linkedin": "",
                "locations": {"ny": "New York, NY", "sf": "San Francisco, CA"}},
    "experiences": [],
    "projects": [],
    "skill_lists": {"developer": {}, "networking": {}, "cybersecurity": {}},
    "education": [],
    "certifications": [],
}


def create_app(
    corpus_path: str = "data/corpus.json",
    config_path: str = "config.yaml",
    apps_root: str = "applications",
) -> FastAPI:
    app = FastAPI(title="Jev Resume Builder")
    ui_html = Path(__file__).resolve().parents[2] / "templates" / "ui.html"

    def _corpus() -> Corpus:
        try:
            return load_corpus(corpus_path)
        except CorpusError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return ui_html.read_text(encoding="utf-8")

    @app.get("/api/config")
    def api_config() -> dict:
        c = _corpus()
        return {
            "corpus_path": corpus_path,
            "has_key": bool(os.environ.get(jev_client.ENV_KEY)),
            "tracks": c.tracks(),
            "locations": c.profile.locations,
            "default_mock": DEFAULT_MOCK,
        }

    @app.get("/api/corpus")
    def api_corpus_get() -> dict:
        p = Path(corpus_path)
        if p.exists():
            try:
                return {"corpus": json.loads(p.read_text(encoding="utf-8")), "path": corpus_path}
            except json.JSONDecodeError as exc:
                raise HTTPException(status_code=400, detail=f"{corpus_path} is not valid JSON: {exc}")
        return {"corpus": EMPTY_CORPUS, "path": corpus_path}

    @app.post("/api/corpus")
    def api_corpus_save(body: dict) -> dict:
        # Validate exactly like the CLI's load_corpus before writing.
        try:
            c = Corpus.model_validate(body)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        p = Path(corpus_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(body, indent=2, ensure_ascii=False), encoding="utf-8")
        return {
            "ok": True,
            "path": corpus_path,
            "experiences": len(c.experiences),
            "projects": len(c.projects),
            "tracks": c.tracks(),
        }

    @app.get("/api/applications")
    def api_applications() -> list[dict]:
        root = Path(apps_root)
        if not root.exists():
            return []
        out = []
        for d in sorted(root.iterdir()):
            if (d / "selected.json").exists():
                out.append({"slug": d.name, "has_polished": (d / "polished.json").exists()})
        return out

    @app.get("/api/application/{slug}")
    def api_application(slug: str) -> dict:
        sel = Path(apps_root) / slug / "selected.json"
        if not sel.exists():
            raise HTTPException(status_code=404, detail=f"no selected.json for {slug!r}")
        selected = json.loads(sel.read_text(encoding="utf-8"))
        return {"selected": selected, "catalog": build_catalog(_corpus())}

    @app.post("/api/select")
    def api_select(body: SelectBody) -> dict:
        if not body.jd.strip():
            raise HTTPException(status_code=400, detail="job description is empty")
        cfg = load_config(config_path)
        corpus = _corpus()
        request = questions.build_request(corpus, body.jd, cfg.jev.model)
        app_dir = Path(apps_root) / body.slug
        mock_path = (body.mock_path or DEFAULT_MOCK) if body.mock else None
        try:
            response, from_cache = jev_client.get_response(
                request,
                app_dir,
                endpoint=cfg.jev.endpoint,
                timeout=cfg.jev.timeout_s,
                mock_path=mock_path,
                refresh=body.refresh,
            )
        except jev_client.JevError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        ov = load_overrides(app_dir / "overrides.yaml")
        ov_warnings = validate_against_corpus(ov, corpus)
        result = run_select(corpus, jev_client.answers_of(response), ov, cfg)
        app_dir.mkdir(parents=True, exist_ok=True)
        (app_dir / "jd.txt").write_text(body.jd, encoding="utf-8")
        (app_dir / "selected.json").write_text(
            json.dumps(result.selected, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return {
            "selected": result.selected,
            "warnings": ov_warnings + result.warnings,
            "from_cache": from_cache,
            "catalog": build_catalog(corpus),
        }

    return app
