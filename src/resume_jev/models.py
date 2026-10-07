"""Pydantic models for the resume corpus (the source of truth) and the
selected-output shape.

IDs must be unique and stable across the whole corpus. Bullet IDs must be
prefixed with their parent's id (e.g. ``exp_startup.b1``). Validation errors on
load are fatal: a typo in an id silently breaks overrides and Jev scoring, so we
fail loudly instead.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_ID_RE = re.compile(r"^[a-z0-9_]+$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}$")


class CorpusError(ValueError):
    """Raised when a corpus fails schema or cross-field validation."""


class Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Bullet(Base):
    id: str
    text: str

    @field_validator("id")
    @classmethod
    def _check_id(cls, v: str) -> str:
        # Bullet ids look like "exp_startup.b1": a parent id, a dot, a suffix.
        if "." not in v or not all(_ID_RE.match(part) for part in v.split(".")):
            raise ValueError(f"bullet id {v!r} must be '<parent_id>.<suffix>' using [a-z0-9_]")
        return v


class Profile(Base):
    name: str
    email: str
    github: str | None = None
    linkedin: str | None = None
    # label -> rendered location string, e.g. {"ny": "New York, NY"}
    locations: dict[str, str]


class Experience(Base):
    id: str
    org: str
    role: str
    location: str
    start: str
    end: str  # "YYYY-MM" or "present"
    summary: str
    bullets: list[Bullet] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _check_id(cls, v: str) -> str:
        if not _ID_RE.match(v):
            raise ValueError(f"id {v!r} must match [a-z0-9_]")
        return v

    @field_validator("start")
    @classmethod
    def _check_start(cls, v: str) -> str:
        if not _DATE_RE.match(v):
            raise ValueError(f"start {v!r} must be 'YYYY-MM'")
        return v

    @field_validator("end")
    @classmethod
    def _check_end(cls, v: str) -> str:
        if v != "present" and not _DATE_RE.match(v):
            raise ValueError(f"end {v!r} must be 'YYYY-MM' or 'present'")
        return v

    @model_validator(mode="after")
    def _check_bullet_prefix(self) -> "Experience":
        for b in self.bullets:
            if b.id.split(".")[0] != self.id:
                raise ValueError(f"bullet {b.id!r} must be prefixed with experience id {self.id!r}")
        return self


class Project(Base):
    id: str
    name: str
    tech: list[str] = Field(default_factory=list)
    link: str | None = None
    summary: str
    bullets: list[Bullet] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _check_id(cls, v: str) -> str:
        if not _ID_RE.match(v):
            raise ValueError(f"id {v!r} must match [a-z0-9_]")
        return v

    @model_validator(mode="after")
    def _check_bullet_prefix(self) -> "Project":
        for b in self.bullets:
            if b.id.split(".")[0] != self.id:
                raise ValueError(f"bullet {b.id!r} must be prefixed with project id {self.id!r}")
        return self


class Education(Base):
    school: str
    degree: str
    dates: str
    details: list[str] = Field(default_factory=list)


class Corpus(Base):
    profile: Profile
    experiences: list[Experience] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    # track -> {category -> [skills]}
    skill_lists: dict[str, dict[str, list[str]]] = Field(default_factory=dict)
    education: list[Education] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_unique_ids(self) -> "Corpus":
        seen: dict[str, str] = {}
        dups: list[str] = []

        def mark(the_id: str, where: str) -> None:
            if the_id in seen:
                dups.append(f"{the_id!r} (in {seen[the_id]} and {where})")
            else:
                seen[the_id] = where

        for e in self.experiences:
            mark(e.id, "experiences")
            for b in e.bullets:
                mark(b.id, f"experience {e.id}")
        for p in self.projects:
            mark(p.id, "projects")
            for b in p.bullets:
                mark(b.id, f"project {p.id}")

        if dups:
            raise ValueError("duplicate ids: " + "; ".join(dups))
        return self

    # --- convenience accessors used across the pipeline ---

    def all_item_ids(self) -> set[str]:
        """Every id a user could pin/ban/nudge (experiences, projects, bullets)."""
        ids: set[str] = set()
        for e in self.experiences:
            ids.add(e.id)
            ids.update(b.id for b in e.bullets)
        for p in self.projects:
            ids.add(p.id)
            ids.update(b.id for b in p.bullets)
        return ids

    def tracks(self) -> list[str]:
        return list(self.skill_lists.keys())


def load_corpus(path: str | Path) -> Corpus:
    """Load and fully validate a corpus JSON file.

    Raises :class:`CorpusError` with a readable message on any problem.
    """
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CorpusError(f"corpus not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise CorpusError(f"corpus is not valid JSON ({path}): {exc}") from exc
    try:
        return Corpus.model_validate(raw)
    except Exception as exc:  # pydantic ValidationError or our ValueErrors
        raise CorpusError(f"corpus failed validation ({path}):\n{exc}") from exc
