from resume_jev.questions import RELEVANCE_RUBRIC, build_questions, build_request, build_state


def test_state_lists_ids(corpus):
    state = build_state(corpus, "We need a backend engineer.")
    assert "We need a backend engineer." in state
    assert "[exp_startup]" in state
    assert "[exp_startup.b1]" in state
    assert "[proj_netmon]" in state


def test_request_shape(corpus):
    req = build_request(corpus, "jd text", "jev-latest")
    # Jev's real top-level shape: model / state / questions only.
    assert set(req.keys()) == {"model", "state", "questions"}
    assert req["model"] == "jev-latest"

    q = req["questions"]
    assert q["role_track"]["type"] == "choice"
    assert set(q["role_track"]["criteria"].keys()) == set(corpus.tracks())
    assert q["location"]["type"] == "choice"
    assert set(q["location"]["criteria"].keys()) == set(corpus.profile.locations.keys())

    # Score questions carry the 6-level rubric array (lowest first); each is
    # keyed by the item's own id (which already encodes kind).
    assert q["exp_startup"]["type"] == "score"
    assert q["exp_startup"]["criteria"] == RELEVANCE_RUBRIC
    assert len(RELEVANCE_RUBRIC) == 6

    # Every experience, project, and bullet has a question.
    assert "proj_netmon" in q
    assert "exp_startup.b1" in q
    assert "proj_netmon.b1" in q


def test_all_bullets_have_questions(corpus):
    q = build_questions(corpus)
    for e in corpus.experiences:
        assert e.id in q
        for b in e.bullets:
            assert b.id in q
    for p in corpus.projects:
        assert p.id in q
        for b in p.bullets:
            assert b.id in q
