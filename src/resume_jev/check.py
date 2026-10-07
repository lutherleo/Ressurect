"""Validate ``polished.json`` against ``selected.json``.

The manual polish pass may only rephrase bullet text. This checker enforces that:

- **Error:** any id added, removed, or reordered; any structural change
  (profile / skills / education / certifications / non-bullet item fields);
  any number/metric changed or added within a bullet.
- **Warning:** a tech-like token (Capitalized / ALLCAPS / in the skills
  vocabulary) appears in polished text but nowhere in the corpus — a possible
  invented claim.
- **Info:** a per-bullet text diff.

``render`` uses ``polished.json`` only when the report has no errors.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .models import Corpus

_NUMBER_RE = re.compile(r"\d[\w.,%+/-]*")
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#./-]*")


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    infos: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def text(self) -> str:
        lines = []
        for e in self.errors:
            lines.append(f"ERROR: {e}")
        for w in self.warnings:
            lines.append(f"WARN:  {w}")
        for i in self.infos:
            lines.append(f"INFO:  {i}")
        if not lines:
            lines.append("OK: polished.json matches selected.json (no changes beyond rephrasing).")
        return "\n".join(lines)


def _numbers(text: str) -> list[str]:
    return sorted(_NUMBER_RE.findall(text or ""))


def _corpus_vocabulary(corpus: Corpus) -> tuple[set[str], set[str]]:
    """Return (all_tokens_lower, skills_tokens_lower) occurring in the corpus."""
    tokens: set[str] = set()

    def add(text: str) -> None:
        for tok in _TOKEN_RE.findall(text or ""):
            tokens.add(tok.lower())

    p = corpus.profile
    for s in (p.name, p.email, p.github or "", p.linkedin or ""):
        add(s)
    for e in corpus.experiences:
        for s in (e.org, e.role, e.location, e.summary):
            add(s)
        for b in e.bullets:
            add(b.text)
    for pr in corpus.projects:
        for s in (pr.name, pr.summary, pr.link or ""):
            add(s)
        for t in pr.tech:
            add(t)
        for b in pr.bullets:
            add(b.text)
    skills: set[str] = set()
    for cats in corpus.skill_lists.values():
        for items in cats.values():
            for s in items:
                add(s)
                for tok in _TOKEN_RE.findall(s):
                    skills.add(tok.lower())
    for ed in corpus.education:
        add(ed.school)
        add(ed.degree)
        for d in ed.details:
            add(d)
    for c in corpus.certifications:
        add(c)
    return tokens, skills


def _invented_tokens(text: str, skills_vocab: set[str], corpus_tokens: set[str]) -> list[str]:
    """Tech-like tokens in `text` that never occur in the corpus.

    A token is flagged when it is in the skills vocabulary, ALL-CAPS (an
    acronym), or CamelCase / contains a digit or special char. A token that is
    merely leading-capital (ordinary sentence case, e.g. "Engineered") is
    flagged only when it is NOT sentence-initial — sentence-initial capitals are
    grammar, not claims.
    """
    flagged: list[str] = []
    prev_end = 0
    for m in _TOKEN_RE.finditer(text):
        tok = m.group()
        if tok.lower() in corpus_tokens:
            prev_end = m.end()
            continue
        # Is this token the first word of the string or of a sentence?
        preceding = text[prev_end : m.start()]
        sentence_initial = m.start() == 0 or bool(re.search(r"[.!?]\s*$", preceding))

        strong = (
            tok.lower() in skills_vocab
            or (tok.isupper() and len(tok) >= 2)
            or any(c.isupper() for c in tok[1:])
            or any(c.isdigit() or c in "+#./-" for c in tok)
        )
        leading_capital = tok[:1].isupper()

        if strong or (leading_capital and not sentence_initial):
            flagged.append(tok)
        prev_end = m.end()
    return flagged


def _bullets_by_id(item: dict) -> dict[str, str]:
    return {b["id"]: b["text"] for b in item.get("bullets", [])}


def _check_section(
    selected: dict, polished: dict, key: str, id_field: str, report: Report, skills_vocab: set[str], corpus_tokens: set[str]
) -> None:
    sel_items = selected.get(key, [])
    pol_items = polished.get(key, [])
    sel_ids = [it[id_field] for it in sel_items]
    pol_ids = [it[id_field] for it in pol_items]
    if sel_ids != pol_ids:
        report.errors.append(
            f"{key}: id order/set changed. selected={sel_ids} polished={pol_ids}"
        )
        return  # can't align further

    pol_by_id = {it[id_field]: it for it in pol_items}
    for sel_it in sel_items:
        the_id = sel_it[id_field]
        pol_it = pol_by_id[the_id]

        # Non-bullet fields must be identical.
        sel_meta = {k: v for k, v in sel_it.items() if k != "bullets"}
        pol_meta = {k: v for k, v in pol_it.items() if k != "bullets"}
        if sel_meta != pol_meta:
            report.errors.append(f"{key} {the_id}: non-bullet fields changed")

        sel_b = _bullets_by_id(sel_it)
        pol_b = _bullets_by_id(pol_it)
        if list(sel_b.keys()) != list(pol_b.keys()):
            report.errors.append(
                f"{key} {the_id}: bullet ids changed. "
                f"selected={list(sel_b.keys())} polished={list(pol_b.keys())}"
            )
            continue

        for bid in sel_b:
            sel_text, pol_text = sel_b[bid], pol_b[bid]
            if _numbers(sel_text) != _numbers(pol_text):
                report.errors.append(
                    f"{bid}: numbers changed. "
                    f"selected={_numbers(sel_text)} polished={_numbers(pol_text)}"
                )
            if sel_text != pol_text:
                report.infos.append(f"{bid}: '{sel_text}' -> '{pol_text}'")
            # Invented-token warnings.
            for tok in _invented_tokens(pol_text, skills_vocab, corpus_tokens):
                report.warnings.append(f"{bid}: '{tok}' does not occur in the corpus")


def check(selected: dict, polished: dict, corpus: Corpus) -> Report:
    report = Report()
    corpus_tokens, skills_vocab = _corpus_vocabulary(corpus)

    # Structural sections that polish must never touch.
    for key in ("profile", "skills", "education", "certifications"):
        if selected.get(key) != polished.get(key):
            report.errors.append(f"{key} changed; polish must not modify it")

    _check_section(selected, polished, "experiences", "id", report, skills_vocab, corpus_tokens)
    _check_section(selected, polished, "projects", "id", report, skills_vocab, corpus_tokens)
    return report
