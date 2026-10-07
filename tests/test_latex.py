from pathlib import Path

from resume_jev.latex import tex_escape
from resume_jev.render import render_tex


def test_escape_special_chars():
    assert tex_escape("a & b") == r"a \& b"
    assert tex_escape("100%") == r"100\%"
    assert tex_escape("C_type") == r"C\_type"
    assert tex_escape("a#b$c") == r"a\#b\$c"
    assert tex_escape("~x^y") == r"\textasciitilde{}x\textasciicircum{}y"
    assert tex_escape(r"a\b") == r"a\textbackslash{}b"
    assert tex_escape(None) == ""


def test_escape_does_not_double_escape():
    # The backslash introduced for & must not itself get escaped again.
    assert tex_escape("&") == r"\&"
    assert "textbackslash" not in tex_escape("&")


def test_render_tex_produces_file(tmp_path):
    selected = {
        "profile": {"name": "A & B", "email": "a@b.com", "github": None, "linkedin": None,
                    "location": "San Francisco, CA"},
        "experiences": [
            {"id": "exp_x", "org": "Org", "role": "Engineer", "location": "SF",
             "start": "2024-01", "end": "present", "summary": "s",
             "bullets": [{"id": "exp_x.b1", "text": "Shipped 100% of the thing"}]}
        ],
        "projects": [],
        "skills": {"Languages": ["Python", "Go"]},
        "education": [],
        "certifications": ["CompTIA Security+ (2024)"],
        "_meta": {},
    }
    templates = Path(__file__).parents[1] / "templates"
    tex_path = render_tex(selected, tmp_path, templates)
    text = tex_path.read_text(encoding="utf-8")
    assert tex_path.name == "resume.tex"
    assert r"A \& B" in text
    assert r"Shipped 100\% of the thing" in text
    assert r"\section{Experience}" in text
    assert r"\section{Skills}" in text
    # No projects section when empty.
    assert r"\section{Projects}" not in text
    # \noindent must be separated from following plain text (no \noindentCompTIA).
    import re as _re
    assert not _re.search(r"\\noindent[A-Za-z]", text)
