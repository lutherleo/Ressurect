"""Deterministic selection: turn Jev answers + overrides into ``selected.json``.

Pure functions, no I/O. Ranking is by **expected score** = Σ level × p (from the
``probabilities`` map), which orders items more finely than the argmax integer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import Config
from .models import Corpus, Experience, Project
from .overrides import Overrides


@dataclass
class SelectionResult:
    selected: dict
    warnings: list[str] = field(default_factory=list)


# --- parsing Jev answers -------------------------------------------------------


def expected_from_probabilities(probabilities: dict[str, float]) -> float:
    """Σ level × p. Keys are stringified integer levels ("0".."5")."""
    return sum(int(level) * p for level, p in probabilities.items())


def _score(answers: dict, qid: str) -> float:
    ans = answers.get(qid)
    if not ans:
        return 0.0
    probs = ans.get("probabilities")
    if probs:
        return expected_from_probabilities(probs)
    # Fall back to Jev's own expected value if probabilities are absent.
    return float(ans.get("score", 0.0))


def _choice(answers: dict, qid: str) -> tuple[str | None, float, dict[str, float]]:
    ans = answers.get(qid)
    if not ans:
        return None, 0.0, {}
    return ans.get("choice"), float(ans.get("confidence", 0.0)), ans.get("probabilities", {})


# --- date ordering -------------------------------------------------------------


def _date_key(ym: str) -> tuple[int, int]:
    if ym == "present":
        return (9999, 99)
    year, month = ym.split("-")
    return (int(year), int(month))


def _reverse_chron(experiences: list[Experience]) -> list[Experience]:
    # Most recent first: sort by end date, then start date, both descending.
    return sorted(experiences, key=lambda e: (_date_key(e.end), _date_key(e.start)), reverse=True)


# --- track / location ----------------------------------------------------------


def select_track(
    corpus: Corpus, answers: dict, ov: Overrides, cfg: Config
) -> tuple[str, bool, dict, list[str]]:
    """Return (track_label, is_hybrid, probabilities, warnings).

    ``track_label`` is a single track, or ``"a+b"`` when the top two are within
    ``track_merge_margin``.
    """
    warnings: list[str] = []
    _, _, probs = _choice(answers, "role_track")
    # Restrict to tracks that actually exist in the corpus.
    probs = {t: probs.get(t, 0.0) for t in corpus.tracks()}

    if ov.force_track is not None:
        return ov.force_track, False, probs, warnings

    if not probs:
        return (corpus.tracks()[0] if corpus.tracks() else "developer"), False, probs, warnings

    ranked = sorted(probs.items(), key=lambda kv: kv[1], reverse=True)
    top_track, top_p = ranked[0]
    if len(ranked) >= 2:
        second_track, second_p = ranked[1]
        if top_p - second_p <= cfg.track_merge_margin:
            label = f"{top_track}+{second_track}"
            return label, True, probs, warnings
    return top_track, False, probs, warnings


def merge_skill_lists(corpus: Corpus, track_label: str, cfg: Config) -> dict[str, list[str]]:
    """Resolve the skills block for a (possibly hybrid "a+b") track label.

    Union per category, dedupe preserving first-seen order, cap per category.
    """
    tracks = track_label.split("+")
    merged: dict[str, list[str]] = {}
    for track in tracks:
        for category, skills in corpus.skill_lists.get(track, {}).items():
            bucket = merged.setdefault(category, [])
            for s in skills:
                if s not in bucket:
                    bucket.append(s)
    # Cap each category.
    return {cat: skills[: cfg.skills_cap_per_category] for cat, skills in merged.items()}


def select_location(
    corpus: Corpus, answers: dict, ov: Overrides, cfg: Config
) -> tuple[str, float, list[str]]:
    """Return (location_label, confidence, warnings)."""
    warnings: list[str] = []
    choice, confidence, _ = _choice(answers, "location")

    if ov.force_location is not None:
        return ov.force_location, 1.0, warnings

    if choice is None or choice not in corpus.profile.locations:
        warnings.append(f"location fallback to default {cfg.default_location!r} (no valid choice)")
        return cfg.default_location, confidence, warnings
    if confidence < cfg.location_confidence_min:
        warnings.append(
            f"location confidence {confidence:.2f} < {cfg.location_confidence_min}; "
            f"using default {cfg.default_location!r}"
        )
        return cfg.default_location, confidence, warnings
    return choice, confidence, warnings


# --- item selection ------------------------------------------------------------


def _nudged(base: float, item_id: str, ov: Overrides) -> float:
    return base + ov.nudge.get(item_id, 0.0)


def _trim_bullets(item: Experience | Project, answers: dict, ov: Overrides, cap: int) -> list[dict]:
    """Keep the top-`cap` bullets by expected score, output in corpus order."""
    scored = [(b, _nudged(_score(answers, b.id), b.id, ov)) for b in item.bullets]
    keep_ids = {b.id for b, _ in sorted(scored, key=lambda t: t[1], reverse=True)[:cap]}
    return [{"id": b.id, "text": b.text} for b in item.bullets if b.id in keep_ids]


def select(
    corpus: Corpus, answers: dict, ov: Overrides, cfg: Config
) -> SelectionResult:
    warnings: list[str] = []
    scores: dict[str, float] = {}

    # ---- track + skills + location ----
    track_label, hybrid, track_probs, w = select_track(corpus, answers, ov, cfg)
    warnings += w
    skills = merge_skill_lists(corpus, track_label, cfg)
    location_label, loc_conf, w = select_location(corpus, answers, ov, cfg)
    warnings += w

    # ---- experiences ----
    exp_scored: dict[str, float] = {}
    for e in corpus.experiences:
        s = _nudged(_score(answers, e.id), e.id, ov)
        exp_scored[e.id] = s
        scores[e.id] = s

    candidates = [e for e in corpus.experiences if e.id not in ov.ban]
    ranked = sorted(candidates, key=lambda e: exp_scored[e.id], reverse=True)
    auto = ranked[: cfg.min_experiences]
    if len(ranked) >= cfg.min_experiences + 1:
        third = ranked[cfg.min_experiences]
        if exp_scored[third.id] >= cfg.third_exp_threshold:
            auto = ranked[: cfg.max_experiences]
    chosen_exp_ids = {e.id for e in auto}
    for e in candidates:
        if e.id in ov.pin:
            chosen_exp_ids.add(e.id)
    if len(chosen_exp_ids) > cfg.max_experiences:
        warnings.append(
            f"{len(chosen_exp_ids)} experiences chosen (> max {cfg.max_experiences}) due to pins"
        )
    chosen_exps = [e for e in corpus.experiences if e.id in chosen_exp_ids]
    chosen_exps = _reverse_chron(chosen_exps)

    out_experiences = []
    for e in chosen_exps:
        for b in e.bullets:
            scores[b.id] = _nudged(_score(answers, b.id), b.id, ov)
        out_experiences.append(
            {
                "id": e.id,
                "org": e.org,
                "role": e.role,
                "location": e.location,
                "start": e.start,
                "end": e.end,
                "summary": e.summary,
                "bullets": _trim_bullets(e, answers, ov, cfg.bullets_per_exp),
            }
        )

    # ---- projects ----
    proj_scored: dict[str, float] = {}
    for p in corpus.projects:
        s = _nudged(_score(answers, p.id), p.id, ov)
        proj_scored[p.id] = s
        scores[p.id] = s

    proj_candidates = [p for p in corpus.projects if p.id not in ov.ban]
    proj_ranked = sorted(proj_candidates, key=lambda p: proj_scored[p.id], reverse=True)
    chosen_proj_ids = {p.id for p in proj_ranked[: cfg.top_projects]}
    for p in proj_candidates:
        if p.id in ov.pin:
            chosen_proj_ids.add(p.id)
    if len(chosen_proj_ids) > cfg.top_projects:
        warnings.append(
            f"{len(chosen_proj_ids)} projects chosen (> top {cfg.top_projects}) due to pins"
        )
    # Projects are ordered by expected score (highest first).
    chosen_projects = [p for p in proj_ranked if p.id in chosen_proj_ids]

    out_projects = []
    for p in chosen_projects:
        for b in p.bullets:
            scores[b.id] = _nudged(_score(answers, b.id), b.id, ov)
        out_projects.append(
            {
                "id": p.id,
                "name": p.name,
                "tech": list(p.tech),
                "link": p.link,
                "summary": p.summary,
                "bullets": _trim_bullets(p, answers, ov, cfg.bullets_per_proj),
            }
        )

    selected = {
        "profile": {
            "name": corpus.profile.name,
            "email": corpus.profile.email,
            "github": corpus.profile.github,
            "linkedin": corpus.profile.linkedin,
            "location": corpus.profile.locations.get(location_label, location_label),
        },
        "experiences": out_experiences,
        "projects": out_projects,
        "skills": skills,
        "education": [e.model_dump() for e in corpus.education],
        "certifications": list(corpus.certifications),
        "_meta": {
            "track": track_label,
            "track_hybrid": hybrid,
            "track_probabilities": track_probs,
            "location": location_label,
            "location_label": corpus.profile.locations.get(location_label, location_label),
            "location_confidence": loc_conf,
            "scores": scores,
            "overrides_applied": ov.model_dump(),
        },
    }
    return SelectionResult(selected=selected, warnings=warnings)
