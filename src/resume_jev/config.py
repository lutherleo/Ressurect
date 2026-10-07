"""Load ``config.yaml`` into a typed object. Defaults mirror the shipped file so
the pipeline still works if a key is missing."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel


class JevConfig(BaseModel):
    endpoint: str = "https://api.typesafe.ai/v1/systemone"
    model: str = "jev-latest"
    timeout_s: int = 30


class Config(BaseModel):
    jev: JevConfig = JevConfig()
    top_projects: int = 3
    min_experiences: int = 2
    max_experiences: int = 3
    third_exp_threshold: float = 3.0
    bullets_per_exp: int = 3
    bullets_per_proj: int = 2
    track_merge_margin: float = 0.20
    skills_cap_per_category: int = 8
    default_location: str = "sf"
    location_confidence_min: float = 0.6


def load_config(path: str | Path = "config.yaml") -> Config:
    path = Path(path)
    if not path.exists():
        return Config()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return Config.model_validate(data)
