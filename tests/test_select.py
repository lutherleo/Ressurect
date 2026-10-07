import pytest

from resume_jev.config import Config
from resume_jev.overrides import Overrides
from resume_jev.select import expected_from_probabilities, select


def score_answer(probabilities: dict[str, float]):
    expected = sum(int(k) * v for k, v in probabilities.items())
    return {"type": "score", "score": expected, "confidence": 0.8, "probabilities": probabilities}


@pytest.fixture
def cfg():
    return Config()


def chosen_exp_ids(result):
    return [e["id"] for e in result.selected["experiences"]]


def chosen_proj_ids(result):
    return [p["id"] for p in result.selected["projects"]]


def test_expected_score_math():
    assert expected_from_probabilities({"0": 0.0, "1": 0.7, "2": 0.3}) == pytest.approx(1.3)
    assert expected_from_probabilities({"4": 0.4, "5": 0.6}) == pytest.approx(4.6)


def test_third_experience_excluded_below_threshold(corpus, answers, cfg):
    # internship_a expected 2.5 < 3.0 -> only top 2 experiences.
    result = select(corpus, answers, Overrides(), cfg)
    assert chosen_exp_ids(result) == ["exp_startup", "exp_research_lab"]


def test_third_experience_included_at_threshold(corpus, answers, cfg):
    answers["exp_internship_a"] = score_answer({"3": 0.9, "4": 0.1})  # 3.1 >= 3.0
    result = select(corpus, answers, Overrides(), cfg)
    assert set(chosen_exp_ids(result)) == {"exp_startup", "exp_research_lab", "exp_internship_a"}


def test_experiences_reverse_chronological(corpus, answers, cfg):
    result = select(corpus, answers, Overrides(), cfg)
    # startup ends "present", research ends 2024-05 -> startup first.
    assert chosen_exp_ids(result) == ["exp_startup", "exp_research_lab"]


def test_ban_excludes_and_pin_includes(corpus, answers, cfg):
    ov = Overrides(ban=["exp_startup"], pin=["exp_internship_b"])
    result = select(corpus, answers, ov, cfg)
    ids = chosen_exp_ids(result)
    assert "exp_startup" not in ids
    assert "exp_internship_b" in ids


def test_nudge_promotes_project(corpus, answers, cfg):
    # proj_todo is lowest (1.0); nudge it above the field.
    ov = Overrides(nudge={"proj_todo": 5.0})
    result = select(corpus, answers, ov, cfg)
    assert "proj_todo" in chosen_proj_ids(result)


def test_bullet_trimming_keeps_corpus_order(corpus, answers, cfg):
    result = select(corpus, answers, Overrides(), cfg)
    startup = next(e for e in result.selected["experiences"] if e["id"] == "exp_startup")
    bullet_ids = [b["id"] for b in startup["bullets"]]
    # 4 bullets, cap 3; b4 (score 2.0) drops; survivors stay in corpus order.
    assert bullet_ids == ["exp_startup.b1", "exp_startup.b2", "exp_startup.b3"]


def test_track_merge_when_within_margin(corpus, answers, cfg):
    answers["role_track"] = {
        "type": "choice", "choice": "developer", "confidence": 0.5,
        "probabilities": {"developer": 0.5, "networking": 0.4, "cybersecurity": 0.1},
    }
    result = select(corpus, answers, Overrides(), cfg)
    meta = result.selected["_meta"]
    assert meta["track_hybrid"] is True
    assert meta["track"] == "developer+networking"
    # Merged skills include categories from both tracks (e.g. networking Protocols).
    assert "Protocols" in result.selected["skills"]


def test_no_merge_when_outside_margin(corpus, answers, cfg):
    # fixture: developer 0.70 vs networking 0.25 -> margin 0.45 > 0.20.
    result = select(corpus, answers, Overrides(), cfg)
    assert result.selected["_meta"]["track_hybrid"] is False
    assert result.selected["_meta"]["track"] == "developer"


def test_location_fallback_on_low_confidence(corpus, answers, cfg):
    answers["location"] = {
        "type": "choice", "choice": "ny", "confidence": 0.4, "probabilities": {"ny": 0.4, "sf": 0.6}
    }
    result = select(corpus, answers, Overrides(), cfg)
    assert result.selected["_meta"]["location"] == cfg.default_location  # "sf"


def test_force_location_overrides(corpus, answers, cfg):
    ov = Overrides(force_location="ny")
    result = select(corpus, answers, ov, cfg)
    assert result.selected["_meta"]["location"] == "ny"
    assert result.selected["profile"]["location"] == "New York, NY"


def test_skills_capped(corpus, answers, cfg):
    cfg.skills_cap_per_category = 2
    result = select(corpus, answers, Overrides(), cfg)
    for items in result.selected["skills"].values():
        assert len(items) <= 2
