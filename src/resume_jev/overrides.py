"""Per-application overrides: pin / ban / nudge / force_track / force_location.

Stored in ``applications/<slug>/overrides.yaml``, never in the corpus. Applied
after Jev scoring and before ranking (see :mod:`resume_jev.select`).
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from .models import Corpus


class Overrides(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pin: list[str] = Field(default_factory=list)
    ban: list[str] = Field(default_factory=list)
    nudge: dict[str, float] = Field(default_factory=dict)
    force_track: str | None = None
    force_location: str | None = None

    def is_empty(self) -> bool:
        return not (self.pin or self.ban or self.nudge or self.force_track or self.force_location)


def empty() -> Overrides:
    return Overrides()


def load_overrides(path: str | Path) -> Overrides:
    """Load overrides from YAML. A missing file is treated as no overrides."""
    path = Path(path)
    if not path.exists():
        return Overrides()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    # Drop keys whose value is null so `force_track: null` means "unset".
    data = {k: v for k, v in data.items() if v is not None}
    return Overrides.model_validate(data)


def validate_against_corpus(ov: Overrides, corpus: Corpus) -> list[str]:
    """Return human-readable warnings for override ids / tracks / locations that
    do not exist in the corpus. Unknown ids are warnings, not errors: a corpus
    can change under a saved override file."""
    warnings: list[str] = []
    item_ids = corpus.all_item_ids()
    for the_id in [*ov.pin, *ov.ban, *ov.nudge.keys()]:
        if the_id not in item_ids:
            warnings.append(f"override references unknown id {the_id!r}")
    both = set(ov.pin) & set(ov.ban)
    if both:
        warnings.append(f"id(s) both pinned and banned (ban wins): {sorted(both)}")
    if ov.force_track is not None and ov.force_track not in corpus.tracks():
        warnings.append(f"force_track {ov.force_track!r} is not a corpus track")
    if ov.force_location is not None and ov.force_location not in corpus.profile.locations:
        warnings.append(f"force_location {ov.force_location!r} is not a corpus location")
    return warnings
