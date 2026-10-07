"""Build the Jev request: the ``state`` string and the ``questions`` map.

Request body (TypeSafe System One, verified 2026-10-06) has three top-level
fields: ``model``, ``state``, ``questions``. This module produces ``state`` and
``questions``; :mod:`resume_jev.jev_client` adds ``model`` and sends it.

Everything here is pure (no I/O, no network) so the generated request can be
snapshot-tested.
"""

from __future__ import annotations

from .models import Corpus

# Shared 0-5 relevance rubric. Jev wants a `score` criteria array, lowest first.
# Index position is the integer level, so this list IS levels 0..5 in order.
RELEVANCE_RUBRIC: list[str] = [
    "Unrelated to the job description.",
    "Tangential; only a transferable soft skill applies.",
    "Same broad field but a different stack or focus.",
    "Matches a nice-to-have requirement.",
    "Directly matches a must-have requirement.",
    "Matches multiple must-have requirements with concrete evidence.",
]

_SCORE_INSTRUCTIONS = (
    "Rate how relevant this item is to the job description. Weight must-have "
    "requirements most heavily. Judge the actual work described, not keyword overlap."
)

# One-line descriptions for the known tracks. Unknown tracks get a generic line.
TRACK_DESCRIPTIONS: dict[str, str] = {
    "developer": "General software engineering: building applications, APIs, and services.",
    "networking": "Networking: protocols, routing, SDN, performance, and infrastructure.",
    "cybersecurity": "Security: application security, threat modeling, offensive/defensive work.",
}


def build_state(corpus: Corpus, jd: str) -> str:
    """Render the program state: the JD, then a delimited listing of every
    experience (with its bullets) and project (with its bullets)."""
    lines: list[str] = []
    lines.append("=== JOB DESCRIPTION ===")
    lines.append(jd.strip())
    lines.append("")
    lines.append("=== CANDIDATE EXPERIENCES ===")
    for e in corpus.experiences:
        lines.append(f"[{e.id}] {e.role} @ {e.org} ({e.start}..{e.end}) — {e.summary}")
        for b in e.bullets:
            lines.append(f"  [{b.id}] {b.text}")
    lines.append("")
    lines.append("=== CANDIDATE PROJECTS ===")
    for p in corpus.projects:
        tech = ", ".join(p.tech)
        lines.append(f"[{p.id}] {p.name} ({tech}) — {p.summary}")
        for b in p.bullets:
            lines.append(f"  [{b.id}] {b.text}")
    return "\n".join(lines)


def _track_criteria(corpus: Corpus) -> dict[str, str]:
    return {
        track: TRACK_DESCRIPTIONS.get(track, f"The {track} role track.")
        for track in corpus.tracks()
    }


def _location_criteria(corpus: Corpus) -> dict[str, str]:
    return {label: f"The job is based in {name}." for label, name in corpus.profile.locations.items()}


def _score_question() -> dict:
    return {"type": "score", "instructions": _SCORE_INSTRUCTIONS, "criteria": list(RELEVANCE_RUBRIC)}


def build_questions(corpus: Corpus) -> dict[str, dict]:
    """Build the full Jev questions map for a corpus."""
    questions: dict[str, dict] = {}

    questions["role_track"] = {
        "type": "choice",
        "instructions": "Which role track does this job description best fit?",
        "criteria": _track_criteria(corpus),
    }
    questions["location"] = {
        "type": "choice",
        "instructions": "Where is this job located? Choose the closest option.",
        "criteria": _location_criteria(corpus),
    }

    # Corpus ids already encode kind (exp_* / proj_* / *.bN), so each score
    # question is keyed by the item's own id — no extra prefix.
    for e in corpus.experiences:
        questions[e.id] = _score_question()
        for b in e.bullets:
            questions[b.id] = _score_question()
    for p in corpus.projects:
        questions[p.id] = _score_question()
        for b in p.bullets:
            questions[b.id] = _score_question()

    return questions


def build_request(corpus: Corpus, jd: str, model: str) -> dict:
    """Assemble the full request body in Jev's real shape."""
    return {
        "model": model,
        "state": build_state(corpus, jd),
        "questions": build_questions(corpus),
    }
