"""Call the Jev (TypeSafe System One) API, with on-disk caching and a mock mode.

Request body (verified against TypeSafe docs, 2026-10-06)::

    POST https://api.typesafe.ai/v1/systemone
    Authorization: Bearer $TYPESAFE_API_KEY
    { "model": ..., "state": ..., "questions": {...} }

Response::

    { "model": ..., "answers": { qid: {...} }, "usage": {...} }

The cache key is sha256 over the canonical request (which already embeds the
corpus-derived state, the JD, the questions, and the model). Re-running
selection after only changing overrides reads the cached ``jev_response.json``
and never calls Jev again (overrides are applied later, in select).
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import httpx

ENV_KEY = "TYPESAFE_API_KEY"


class JevError(RuntimeError):
    pass


def request_hash(request: dict) -> str:
    canonical = json.dumps(request, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _request_path(app_dir: Path) -> Path:
    return app_dir / "jev_request.json"


def _response_path(app_dir: Path) -> Path:
    return app_dir / "jev_response.json"


def load_cached_response(app_dir: str | Path) -> dict | None:
    path = _response_path(Path(app_dir))
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def answers_of(response: dict) -> dict:
    return response.get("answers", {})


def _cache_valid(app_dir: Path, request: dict) -> bool:
    req_path = _request_path(app_dir)
    if not (req_path.exists() and _response_path(app_dir).exists()):
        return False
    cached_req = json.loads(req_path.read_text(encoding="utf-8"))
    return request_hash(cached_req) == request_hash(request)


def _save_call(app_dir: Path, request: dict, response: dict) -> None:
    app_dir.mkdir(parents=True, exist_ok=True)
    _request_path(app_dir).write_text(
        json.dumps(request, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    _response_path(app_dir).write_text(
        json.dumps(response, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _post(request: dict, *, endpoint: str, timeout: float) -> dict:
    api_key = os.environ.get(ENV_KEY)
    if not api_key:
        raise JevError(
            f"{ENV_KEY} is not set. Export your TypeSafe API key, or use --mock <file> "
            "to run against a canned response."
        )
    try:
        resp = httpx.post(
            endpoint,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=request,
            timeout=timeout,
        )
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise JevError(f"Jev returned {exc.response.status_code}: {exc.response.text}") from exc
    except httpx.HTTPError as exc:
        raise JevError(f"Jev request failed: {exc}") from exc
    return resp.json()


def get_response(
    request: dict,
    app_dir: str | Path,
    *,
    endpoint: str,
    timeout: float,
    mock_path: str | Path | None = None,
    refresh: bool = False,
) -> tuple[dict, bool]:
    """Return (response, from_cache).

    - If a cached response for this exact request exists and ``refresh`` is
      False, reuse it.
    - Otherwise fetch (from ``mock_path`` if given, else the live API), persist
      the request+response, and return it.
    """
    app_dir = Path(app_dir)
    if not refresh and _cache_valid(app_dir, request):
        return load_cached_response(app_dir), True  # type: ignore[return-value]

    if mock_path is not None:
        response = json.loads(Path(mock_path).read_text(encoding="utf-8"))
    else:
        response = _post(request, endpoint=endpoint, timeout=timeout)

    _save_call(app_dir, request, response)
    return response, False
