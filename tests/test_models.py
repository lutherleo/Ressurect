import json

import pytest

from resume_jev.models import CorpusError, load_corpus


def test_fixture_corpus_loads(corpus):
    assert corpus.profile.name == "Alex Rivera"
    assert len(corpus.experiences) == 4
    assert "developer" in corpus.tracks()


def test_duplicate_id_errors(tmp_path):
    data = {
        "profile": {"name": "X", "email": "x@x.com", "locations": {"sf": "SF"}},
        "experiences": [
            {"id": "exp_a", "org": "O", "role": "R", "location": "L",
             "start": "2024-01", "end": "present", "summary": "s", "bullets": []},
            {"id": "exp_a", "org": "O2", "role": "R2", "location": "L",
             "start": "2023-01", "end": "2023-06", "summary": "s", "bullets": []},
        ],
    }
    p = tmp_path / "c.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(CorpusError, match="duplicate ids"):
        load_corpus(p)


def test_bullet_prefix_enforced(tmp_path):
    data = {
        "profile": {"name": "X", "email": "x@x.com", "locations": {"sf": "SF"}},
        "experiences": [
            {"id": "exp_a", "org": "O", "role": "R", "location": "L",
             "start": "2024-01", "end": "present", "summary": "s",
             "bullets": [{"id": "exp_b.b1", "text": "mismatched prefix"}]},
        ],
    }
    p = tmp_path / "c.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(CorpusError, match="prefixed"):
        load_corpus(p)


def test_bad_date_errors(tmp_path):
    data = {
        "profile": {"name": "X", "email": "x@x.com", "locations": {"sf": "SF"}},
        "experiences": [
            {"id": "exp_a", "org": "O", "role": "R", "location": "L",
             "start": "2024", "end": "present", "summary": "s", "bullets": []},
        ],
    }
    p = tmp_path / "c.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(CorpusError):
        load_corpus(p)
