"""Printable test papers and answer keys as self-contained HTML (open in any browser, print or save as PDF)."""

from __future__ import annotations

import html
import json

from src.modules.studyforge import marking
from src.modules.studyforge.models import ORIGINS, QTYPES

CSS = """
body { font-family: Georgia, 'Times New Roman', serif; max-width: 780px; margin: 32px auto; color: #222; line-height: 1.5; }
h1 { font-size: 22px; margin-bottom: 2px; } .meta { color: #555; font-size: 13px; margin-bottom: 18px; }
h2 { font-size: 16px; border-bottom: 1px solid #ccc; padding-bottom: 4px; margin-top: 26px; }
.q { margin: 14px 0; page-break-inside: avoid; } .marks { float: right; color: #555; font-size: 13px; }
.opts { margin: 6px 0 0 22px; } .src { color: #777; font-size: 11px; } .or { text-align: center; font-style: italic; color: #666; }
.key { background: #f4f4ee; padding: 6px 10px; border-radius: 6px; margin-top: 6px; font-size: 14px; }
.notice { border: 1px solid #ccc; padding: 8px 12px; border-radius: 6px; font-size: 12px; color: #444; }
@media print { body { margin: 0 auto; } }
"""


def paper_html(test, items, with_key: bool = False, course_name: str = "") -> str:
    e = html.escape
    parts = [f"<!doctype html><html><head><meta charset='utf-8'><title>{e(test.title)}</title><style>{CSS}</style>"
             "</head><body>"]
    parts.append(f"<h1>{e(test.title)}{' — Answer key' if with_key else ''}</h1>")
    meta = [course_name] if course_name else []
    meta.append(f"Maximum marks: {test.total_marks:g}")
    if test.duration_min:
        meta.append(f"Time: {test.duration_min} minutes")
    parts.append(f"<div class='meta'>{e(' · '.join(meta))}</div>")
    origins = {json.loads(it.snapshot).get("origin") for it in items}
    note = ("Practice paper made with DayOS from your question bank. It is not an official paper and does not "
            "predict the actual examination.")
    if "ai" in origins:
        note += " Some questions are AI-generated practice questions (marked “AI”)."
    parts.append(f"<p class='notice'>{e(note)}</p>")
    if test.instructions:
        parts.append(f"<p>{e(test.instructions).replace(chr(10), '<br>')}</p>")
    section = None
    number = 0
    last_group = None
    for it in items:
        q = it.question
        if it.section and it.section != section:
            section = it.section
            parts.append(f"<h2>{e(section)}</h2>")
        if it.choice_group is not None and it.choice_group == last_group:
            parts.append("<div class='or'>OR</div>")
        else:
            number += 1
        last_group = it.choice_group
        tag = " · AI" if q.get("origin") == "ai" else (" · official" if q.get("origin") == "official" else "")
        parts.append("<div class='q'>")
        parts.append(f"<span class='marks'>[{it.marks:g}]</span><b>{number}.</b> "
                     f"{e(q.get('text', '')).replace(chr(10), '<br>')}")
        options = marking.question_options(q)
        if q.get("qtype") == "assertion":
            from src.modules.studyforge.models import ASSERTION_OPTIONS

            options = ASSERTION_OPTIONS
        if q.get("qtype") == "match":
            pairs = marking.match_pairs(options)
            rights = sorted(r for _, r in pairs)
            parts.append("<div class='opts'>" + "<br>".join(
                f"{e(l)} &nbsp;&nbsp;&nbsp; {chr(97 + i)}. {e(r)}" for i, ((l, _), r) in enumerate(zip(pairs, rights)))
                + "</div>")
        elif options:
            parts.append("<div class='opts'>" + "<br>".join(f"({chr(97 + i)}) {e(o)}" for i, o in enumerate(options))
                         + "</div>")
        parts.append(f"<div class='src'>{e(QTYPES.get(q.get('qtype', ''), ''))}{e(tag)}"
                     f"{(' · ' + e(q.get('source_ref', ''))) if q.get('source_ref') else ''}</div>")
        if with_key:
            key = marking.expected_answer_text(q) or q.get("answer", "")
            points = marking.rubric_points(q)
            body = f"<b>Answer:</b> {e(key)}" if key else "<b>Answer:</b> (no model answer recorded)"
            if points:
                body += "<br><b>Marking points:</b><br>" + "<br>".join(
                    f"• {e(p['text'])} ({float(p.get('marks', 1)):g})" for p in points)
            if q.get("explanation"):
                body += f"<br><b>Explanation:</b> {e(q['explanation'])}"
            parts.append(f"<div class='key'>{body}</div>")
        parts.append("</div>")
    parts.append(f"<p class='src'>Question sources: {e(', '.join(ORIGINS[o] for o in sorted(origins) if o in ORIGINS))}</p>")
    parts.append("</body></html>")
    return "".join(parts)
