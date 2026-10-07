import copy
import json
from pathlib import Path

import pytest

from resume_jev.models import load_corpus

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def corpus():
    return load_corpus(FIXTURES / "corpus.json")


@pytest.fixture
def jev_response():
    return json.loads((FIXTURES / "jev_response.json").read_text(encoding="utf-8"))


@pytest.fixture
def answers(jev_response):
    # A fresh deep copy so a test mutating answers can't leak into another.
    return copy.deepcopy(jev_response["answers"])
