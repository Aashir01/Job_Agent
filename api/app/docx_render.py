"""Fixed python-docx resume template (§6 Tailor).

Single column. No tables, no text boxes, no headers or footers, standard
section names. Every one of those is an ATS parser failure mode, so the
template has no switches — the Tailor picks content, never layout.
"""
from __future__ import annotations

import io
from typing import Any, Sequence

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt, RGBColor

# Section names ATS parsers recognise. Do not get creative here.
SECTION_SUMMARY = "Summary"
SECTION_SKILLS = "Skills"
SECTION_EXPERIENCE = "Experience"
SECTION_PROJECTS = "Projects"
SECTION_EDUCATION = "Education"

BODY_FONT = "Calibri"
BODY_SIZE = Pt(10.5)
NAME_SIZE = Pt(20)
HEADING_SIZE = Pt(12)
INK = RGBColor(0x11, 0x11, 0x11)
MUTED = RGBColor(0x44, 0x44, 0x44)


def _configure(document: Document) -> None:
    style = document.styles["Normal"]
    style.font.name = BODY_FONT
    style.font.size = BODY_SIZE
    style.font.color.rgb = INK
    fmt = style.paragraph_format
    fmt.space_before = Pt(0)
    fmt.space_after = Pt(2)
    fmt.line_spacing = 1.05
    for section in document.sections:
        section.top_margin = section.bottom_margin = Inches(0.5)
        section.left_margin = section.right_margin = Inches(0.6)


def _heading(document: Document, text: str) -> None:
    para = document.add_paragraph()
    para.paragraph_format.space_before = Pt(9)
    para.paragraph_format.space_after = Pt(3)
    run = para.add_run(text.upper())
    run.bold = True
    run.font.size = HEADING_SIZE
    run.font.color.rgb = INK
    # A bottom border is the one bit of chrome that survives every parser.
    para.paragraph_format.tab_stops.add_tab_stop(Inches(7.3))


def _bullet(document: Document, text: str) -> None:
    para = document.add_paragraph(style="List Bullet")
    para.paragraph_format.left_indent = Inches(0.18)
    para.paragraph_format.space_after = Pt(2)
    para.add_run(text)


def render_resume(
    profile: dict[str, Any],
    experience: Sequence[dict[str, Any]],
    skills: Sequence[str],
    summary: str = "",
    projects: Sequence[dict[str, Any]] = (),
    education: Sequence[dict[str, Any]] = (),
) -> bytes:
    """Render to .docx bytes. Bullets arrive already selected and vetted."""
    document = Document()
    _configure(document)

    name_para = document.add_paragraph()
    name_para.alignment = WD_ALIGN_PARAGRAPH.LEFT
    name_run = name_para.add_run(profile.get("full_name") or "")
    name_run.bold = True
    name_run.font.size = NAME_SIZE

    if headline := profile.get("headline"):
        head = document.add_paragraph()
        run = head.add_run(headline)
        run.font.size = Pt(11)
        run.font.color.rgb = MUTED

    links = profile.get("links") or {}
    contact_bits = [profile.get("location"), profile.get("email"), profile.get("phone")]
    contact_bits += [links.get(k) for k in ("linkedin", "github", "portfolio", "upwork")]
    contact = " | ".join(b for b in contact_bits if b)
    if contact:
        para = document.add_paragraph()
        run = para.add_run(contact)
        run.font.size = Pt(9.5)
        run.font.color.rgb = MUTED

    if summary:
        _heading(document, SECTION_SUMMARY)
        document.add_paragraph(summary)

    if skills:
        _heading(document, SECTION_SKILLS)
        document.add_paragraph(" • ".join(skills))

    if experience:
        _heading(document, SECTION_EXPERIENCE)
        for role in experience:
            line = document.add_paragraph()
            line.paragraph_format.space_before = Pt(5)
            title_run = line.add_run(
                f"{role.get('title', '')} — {role.get('company', '')}".strip(" —")
            )
            title_run.bold = True
            meta_bits = [role.get("location"), role.get("dates")]
            if meta := "  ".join(b for b in meta_bits if b):
                meta_run = line.add_run(f"    {meta}")
                meta_run.font.size = Pt(9.5)
                meta_run.font.color.rgb = MUTED
            for bullet in role.get("bullets") or []:
                _bullet(document, bullet)

    if projects:
        _heading(document, SECTION_PROJECTS)
        for project in projects:
            line = document.add_paragraph()
            line.paragraph_format.space_before = Pt(4)
            run = line.add_run(project.get("name", ""))
            run.bold = True
            if link := project.get("link"):
                link_run = line.add_run(f"    {link}")
                link_run.font.size = Pt(9.5)
                link_run.font.color.rgb = MUTED
            for bullet in project.get("bullets") or []:
                _bullet(document, bullet)

    if education:
        _heading(document, SECTION_EDUCATION)
        for entry in education:
            para = document.add_paragraph()
            run = para.add_run(entry.get("degree", ""))
            run.bold = True
            tail_bits = [entry.get("institution"), entry.get("dates")]
            if tail := " — ".join(b for b in tail_bits if b):
                para.add_run(f"  {tail}")

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()
