import copy

import pytest

from resume_jev.check import check
from resume_jev.config import Config
from resume_jev.overrides import Overrides
from resume_jev.select import select


@pytest.fixture
def selected(corpus, answers):
    return select(corpus, answers, Overrides(), Config()).selected


def test_pure_rephrase_passes(corpus, selected):
    polished = copy.deepcopy(selected)
    b = polished["experiences"][0]["bullets"][0]
    # Rephrase wording only; keep ids and numbers.
    b["text"] = "Engineered a FastAPI service ingesting telemetry from 12k edge devices at 4k msgs/sec."
    report = check(selected, polished, corpus)
    assert report.ok, report.text()


def test_changed_number_errors(corpus, selected):
    polished = copy.deepcopy(selected)
    b = polished["experiences"][0]["bullets"][0]
    b["text"] = b["text"].replace("12k", "50k")
    report = check(selected, polished, corpus)
    assert not report.ok
    assert any("numbers changed" in e for e in report.errors)


def test_dropped_id_errors(corpus, selected):
    polished = copy.deepcopy(selected)
    polished["experiences"][0]["bullets"].pop()
    report = check(selected, polished, corpus)
    assert not report.ok


def test_reordered_experiences_errors(corpus, selected):
    polished = copy.deepcopy(selected)
    polished["experiences"].reverse()
    report = check(selected, polished, corpus)
    assert not report.ok


def test_invented_token_warns(corpus, selected):
    polished = copy.deepcopy(selected)
    b = polished["experiences"][0]["bullets"][0]
    b["text"] = b["text"].rstrip(".") + " using Kubernetes."
    report = check(selected, polished, corpus)
    assert report.ok  # a warning, not an error
    assert any("Kubernetes" in w for w in report.warnings)


def test_structural_change_errors(corpus, selected):
    polished = copy.deepcopy(selected)
    polished["skills"]["Languages"] = ["Rust"]
    report = check(selected, polished, corpus)
    assert not report.ok
    assert any("skills" in e for e in report.errors)
