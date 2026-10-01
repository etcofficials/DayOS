"""StudyForge: course map, question bank, marking, assembly, attempts, revision, import parsing."""

import json
import unittest
import zipfile
from datetime import timedelta

from src.modules.studyforge import marking, srs
from src.modules.studyforge.assembler import Picked, TestConfig, assemble, quick_sections, validate
from src.modules.studyforge.extract import extract
from src.modules.studyforge.models import Question, Section, TopicState
from src.modules.studyforge.paperparse import apply_answer_key, parse_answer_key, parse_paper
from src.modules.studyforge.printable import paper_html
from src.modules.studyforge.repository import DuplicateQuestion, StudyForge
from src.modules.studyforge.service import GenerateRequest, StudyForgeService
from src.modules.studyforge.syllabus import from_lines, parse
from src.modules.studyforge.templates import STARTER_SOURCE, create_cbse10
from src.services.dates import ValidationError
from src.services.transfer import unexported_tables
from tests.helpers import FIXED_NOW, TempHomeTestCase

TODAY = FIXED_NOW.date()


def tiny_pdf(lines: list[str], blank_pages: int = 0) -> bytes:
    """A minimal valid PDF with one text page (+ optional blank pages), built by hand."""
    content = "BT /F1 12 Tf 50 750 Td 14 TL " + " ".join(f"({l}) '" for l in lines) + " ET"
    objs = ["<< /Type /Catalog /Pages 2 0 R >>"]
    kids = " ".join(f"{3 + i * 2} 0 R" for i in range(1 + blank_pages))
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {1 + blank_pages} >>")
    font_obj = 3 + (1 + blank_pages) * 2
    for i in range(1 + blank_pages):
        stream = content if i == 0 else ""
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {4 + i * 2} 0 R "
                    f"/Resources << /Font << /F1 {font_obj} 0 R >> >> >>")
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
    objs.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = b"%PDF-1.4\n"
    offsets = []
    for i, o in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return out


class StudyForgeDataTests(TempHomeTestCase):
    def setUp(self):
        super().setUp()
        self.sf = StudyForge(self.ctx.db)
        self.svc = StudyForgeService(self.sf)
        self.cid = self.sf.courses.create("Physics", "school", "2026–27", "Board")
        self.subj = self.sf.courses.add_node(self.cid, "subject", "Physics")
        self.ch1 = self.sf.courses.add_node(self.cid, "chapter", "Motion", self.subj)
        self.ch2 = self.sf.courses.add_node(self.cid, "chapter", "Force", self.subj)
        self.t1 = self.sf.courses.add_node(self.cid, "topic", "Speed", self.ch1)

    def mcq(self, text, node, answer=0, marks=1.0, **kw):
        return self.sf.bank.add(self.cid, "mcq", text, node_id=node, options=["A", "B", "C", "D"], answer=answer,
                                marks=marks, **kw)

    def test_course_tree_and_paths(self):
        self.assertEqual(self.sf.courses.descendants([self.subj]), {self.subj, self.ch1, self.ch2, self.t1})
        self.assertEqual(self.sf.courses.path_text(self.t1), "Physics › Motion › Speed")
        tree = self.sf.courses.tree(self.cid)
        self.assertEqual([c.title for c in tree[0].children], ["Motion", "Force"])
        self.sf.courses.move_node(self.ch2, -1)
        self.assertEqual([c.title for c in self.sf.courses.children(self.cid, self.subj)], ["Force", "Motion"])
        self.assertEqual({n.id for n in self.sf.courses.topic_nodes(self.cid)}, {self.ch2, self.t1})
        with self.assertRaises(ValidationError):
            self.sf.courses.add_node(self.cid, "galaxy", "x")

    def test_question_validation_and_duplicates(self):
        self.mcq("What is speed?", self.t1)
        with self.assertRaises(DuplicateQuestion):
            self.mcq("  what is SPEED? ", self.t1)
        with self.assertRaises(ValidationError):
            self.sf.bank.add(self.cid, "mcq", "No options", options=["only"], answer=0)
        with self.assertRaises(ValidationError):
            self.sf.bank.add(self.cid, "sa", "Explain inertia")  # no model answer or rubric
        qid = self.sf.bank.add(self.cid, "sa", "Explain inertia", rubric=[{"text": "defines inertia", "marks": 1},
                                                                       {"text": "gives example", "marks": 1}], marks=2)
        self.assertEqual(len(self.sf.bank.get(qid).rubric_points), 2)
        num = self.sf.bank.add(self.cid, "numerical", "g?", answer={"value": 9.8, "tolerance": 0.1, "unit": "m/s²"})
        self.assertEqual(json.loads(self.sf.bank.get(num).answer)["value"], 9.8)
        keyless = self.sf.bank.add(self.cid, "mcq", "Imported without key", options=["x", "y"], origin="imported",
                                   allow_missing_key=True)
        self.assertEqual(self.sf.bank.get(keyless).answer, "")
        with self.assertRaises(ValidationError):
            self.sf.bank.add(self.cid, "mcq", "Own question without key", options=["x", "y"], allow_missing_key=True)

    def test_objective_marking(self):
        mk = marking.mark
        self.assertEqual(mk({"qtype": "mcq", "answer": "2"}, "2", 1).marks, 1)
        self.assertEqual(mk({"qtype": "mcq", "answer": "2"}, "1", 1).marks, 0)
        self.assertIsNone(mk({"qtype": "mcq", "answer": ""}, "1", 1).marks)  # no key: manual
        self.assertEqual(mk({"qtype": "multi", "answer": "[0, 2]"}, "[2, 0]", 2).marks, 2)
        self.assertEqual(mk({"qtype": "tf", "answer": "false"}, "False", 1).marks, 1)
        self.assertEqual(mk({"qtype": "fill", "answer": "photosynthesis|photo-synthesis"}, " Photosynthesis.", 1).marks, 1)
        num = {"qtype": "numerical", "answer": json.dumps({"value": 9.8, "tolerance": 0.05})}
        self.assertEqual(mk(num, "9.83", 1).marks, 1)
        self.assertEqual(mk(num, "9.9", 1).marks, 0)
        match = {"qtype": "match", "options": json.dumps(["H2O => water", "NaCl => salt"]), "answer": ""}
        self.assertEqual(mk(match, json.dumps({"H2O": "water", "NaCl": "sugar"}), 2).marks, 1.0)
        self.assertIsNone(mk({"qtype": "la", "answer": "x"}, "essay", 5).marks)
        self.assertEqual(marking.rubric_score([{"text": "a", "marks": 2}, {"text": "b", "marks": 2}], [True, True], 3), 3)

    def test_assembly_respects_sections_choice_and_reports_shortfalls(self):
        for i in range(6):
            self.mcq(f"Motion question {i}", self.t1 if i % 2 else self.ch1)
        for i in range(3):
            self.mcq(f"Force question {i}", self.ch2)
        for i in range(2):
            self.sf.bank.add(self.cid, "sa", f"Explain force {i}", node_id=self.ch2, marks=3, answer="model")
        bank = self.sf.bank.list(self.cid)
        scope = self.sf.courses.descendants([self.subj])
        cfg = TestConfig([Section("A", "mcq", 6, 1), Section("B", "sa", 1, 3, choice=1)], scope, seed=1)
        result = assemble(bank, cfg, self.svc.chapter_map(self.cid))
        self.assertEqual(result.problems, [])
        self.assertEqual(result.total_marks, 9)
        groups = [it.choice_group for it in result.items if it.section == "B"]
        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[0], groups[1])
        chapters = {self.svc.chapter_map(self.cid)[it.question.node_id] for it in result.items if it.section == "A"}
        self.assertEqual(chapters, {self.ch1, self.ch2})  # coverage spread across chapters
        self.assertEqual(validate(result.items, cfg.sections, 9.0), [])
        cfg2 = TestConfig([Section("C", "la", 2, 5)], scope)
        self.assertIn("bank has 0", assemble(bank, cfg2).problems[0])
        dup = [Picked(bank[0], "A", 1), Picked(bank[0], "A", 1)]
        self.assertTrue(any("more than once" in i for i in validate(dup)))
        self.assertEqual(sum(s.count for s in quick_sections(["mcq", "tf"], 5)), 5)

    def test_generate_take_submit_updates_revision_and_mistakes(self):
        for i in range(4):
            self.mcq(f"Q{i}", self.t1, answer=0)
        self.sf.bank.add(self.cid, "sa", "Describe uniform motion", node_id=self.ch1, marks=2,
                         rubric=[{"text": "constant speed", "marks": 1}, {"text": "straight line", "marks": 1}])
        res = self.svc.generate(GenerateRequest(self.cid, "Motion check", [self.ch1],
                                                sections=quick_sections(["mcq"], 4) + [Section("Written", "sa", 1, 2)],
                                                seed=3))
        self.assertIsNotNone(res.test_id)
        items = self.sf.tests.items(res.test_id)
        self.assertEqual(len(items), 5)
        attempt = self.sf.tests.start_attempt(res.test_id)
        for it in items:
            if it.question["qtype"] == "mcq":
                self.sf.tests.save_answer(attempt, it.id, "0" if it.position < 2 else "1")
            else:
                self.sf.tests.save_answer(attempt, it.id, "It moves at constant speed")
        summary = self.svc.submit(attempt, elapsed_s=300)
        self.assertEqual((summary.auto_marked, summary.needs_marking, summary.mistakes_added), (4, 1, 2))
        self.assertEqual(self.sf.tests.attempt(attempt).status, "submitted")  # written answer still unmarked
        written = next(it for it in items if it.question["qtype"] == "sa")
        with self.assertRaises(ValidationError):
            self.svc.mark_written(attempt, written.id, 3)
        # an AI estimate is stored separately and never feeds the revision schedule
        before = self.sf.revision.state(self.ch1).attempts
        self.svc.mark_written(attempt, written.id, 2, "AI estimate", marker="ai")
        self.assertEqual(self.sf.revision.state(self.ch1).attempts, before)
        self.assertTrue(self.sf.tests.attempt(attempt).has_estimates)
        self.assertEqual(self.svc.analytics(self.cid)["estimated_answers"], 1)
        # the user's own mark overrides the estimate
        self.svc.mark_written(attempt, written.id, 1, "missed straight line")
        a = self.sf.tests.attempt(attempt)
        self.assertEqual((a.status, a.score, a.max_score, a.has_estimates), ("marked", 3.0, 6.0, 0))
        with self.assertRaises(ValidationError):
            self.svc.mark_written(attempt, written.id, 2, "AI again", marker="ai")
        st = self.sf.revision.state(self.t1)
        self.assertEqual(st.attempts, 1)
        self.assertEqual(srs.mastery(st, [str(TODAY)]), "learning")
        self.assertEqual(len(self.sf.mistakes.list(course_node_ids={self.t1, self.ch1})), 2)  # half marks isn't a mistake
        self.assertEqual(self.sf.revision.state(self.ch1).attempts, before + 1)
        stats = self.svc.analytics(self.cid)
        self.assertEqual(stats["history"][0]["percent"], 50.0)

    def test_internal_choice_counts_answered_alternative(self):
        for i in range(2):
            self.sf.bank.add(self.cid, "sa", f"Choice q {i}", node_id=self.ch2, marks=2, answer="model")
        res = self.svc.generate(GenerateRequest(self.cid, "Choice", [self.ch2],
                                                sections=[Section("S", "sa", 1, 2, choice=1)], seed=1))
        items = self.sf.tests.items(res.test_id)
        self.assertEqual(self.sf.tests.test(res.test_id).total_marks, 2)
        attempt = self.sf.tests.start_attempt(res.test_id)
        self.sf.tests.save_answer(attempt, items[1].id, "my answer")
        self.svc.submit(attempt)
        self.svc.mark_written(attempt, items[1].id, 2)
        self.assertEqual((self.sf.tests.attempt(attempt).score, self.sf.tests.attempt(attempt).max_score), (2, 2))

    def test_spaced_revision_is_cautious(self):
        st = TopicState(node_id=1)
        day = TODAY
        st = srs.update_topic(st, 1.0, day)
        self.assertEqual((st.interval_days, srs.mastery(st, [str(day)])), (1, "developing"))
        st = srs.update_topic(st, 1.0, day + timedelta(days=1))
        st = srs.update_topic(st, 0.9, day + timedelta(days=4))
        self.assertEqual(srs.mastery(st, [str(day), str(day + timedelta(days=4))]), "learning" if False else "developing")
        st = srs.update_topic(st, 1.0, day + timedelta(days=12))
        self.assertEqual(srs.mastery(st, [str(day), str(day + timedelta(days=12))]), "strong")
        lapsed = srs.update_topic(st, 0.2, day + timedelta(days=13))
        self.assertEqual((lapsed.interval_days, lapsed.reps, lapsed.lapses), (1, 0, 1))
        capped = srs.update_topic(st, 1.0, day, exam=day + timedelta(days=6))
        self.assertLessEqual(capped.interval_days, 3)

    def test_queue_explains_reasons_and_manual_reschedule(self):
        self.sf.courses.update_node(self.subj, exam_date=TODAY + timedelta(days=10))
        queue = self.svc.queue(self.cid)
        self.assertEqual({q.node.id for q in queue}, {self.t1, self.ch2})
        self.assertTrue(any("Exam in 10 days" in r for r in queue[0].reasons))
        self.svc.record_practice(self.t1, 1.0, "recall")
        self.assertNotIn(self.t1, {q.node.id for q in self.svc.queue(self.cid)})
        self.svc.reschedule(self.t1, TODAY)
        item = next(q for q in self.svc.queue(self.cid) if q.node.id == self.t1)
        self.assertIn("You scheduled it for today", item.reasons)

    def test_flashcards_and_mistake_retries(self):
        cid = self.sf.revision.add_card(self.cid, "v = ?", "d / t", node_id=self.t1, kind="formula")
        card = self.sf.revision.card(cid)
        updated = self.svc.grade_card(card, "good")
        self.assertEqual(updated.interval_days, 1)
        self.assertEqual(self.sf.revision.cards(self.cid, due_only=True), [])
        again = self.svc.grade_card(self.sf.revision.card(cid), "again")
        self.assertEqual(again.due_date, str(TODAY))
        mid = self.sf.mistakes.add("2+2=5", node_id=self.t1, category="Calculation error")
        for _ in range(3):
            self.sf.mistakes.retried(mid, True)
        self.assertEqual(self.sf.mistakes.list(status="resolved")[0]["id"], mid)
        self.assertIn("Time-management issue", self.sf.mistakes.categories())

    def test_blueprint_rules(self):
        sections = [Section("A", "mcq", 10, 1), Section("B", "sa", 5, 3)]
        bid = self.sf.tests.save_blueprint(self.cid, "Term test", 25, 60, sections, status="provisional")
        self.assertEqual(self.sf.tests.blueprint(bid).section_list[1].total, 15)
        with self.assertRaises(ValidationError):
            self.sf.tests.save_blueprint(self.cid, "Wrong total", 30, 60, sections)
        with self.assertRaises(ValidationError):
            self.sf.tests.save_blueprint(self.cid, "Unsourced", 25, 60, sections, status="verified")

    def test_question_bank_export_import(self):
        self.mcq("Exported?", self.t1, origin="official", source_ref="Paper 1, Q1")
        data = self.sf.bank.export(self.cid)
        other = self.sf.courses.create("Copy")
        added, dupes, problems = self.sf.bank.import_items(other, data + [{"qtype": "bad", "text": "x"}])
        self.assertEqual((added, dupes, len(problems)), (1, 0, 1))
        self.assertEqual(self.sf.bank.list(other)[0].origin, "imported")  # files can't prove officialness
        self.assertEqual(self.sf.bank.import_items(other, data)[1], 1)

    def test_cbse_starter_is_provisional(self):
        course = create_cbse10(self.sf, "2026–27", ["Mathematics", "Science"], {"Science": TODAY + timedelta(days=90)},
                               True, "Mathematics Basic", self.ctx.subjects)
        nodes = self.sf.courses.nodes(course)
        chapters = [n for n in nodes if n.kind == "chapter"]
        self.assertTrue(chapters)
        self.assertTrue(all(n.source_ref == STARTER_SOURCE and n.confidence == 0.7 for n in chapters))
        self.assertIn("Mathematics Basic", [n.title for n in nodes if n.kind == "subject"])
        self.assertIn("Mathematics Basic", [s.name for s in self.ctx.subjects.list()])

    def test_printable_paper_has_disclaimer(self):
        self.mcq("Printable?", self.t1)
        res = self.svc.generate(GenerateRequest(self.cid, "Print me", [self.t1], sections=quick_sections(["mcq"], 1)))
        test = self.sf.tests.test(res.test_id)
        html = paper_html(test, self.sf.tests.items(test.id), with_key=True)
        self.assertIn("not an official paper", html)
        self.assertIn("Answer:", html)

    def test_everything_is_exported(self):
        self.assertEqual(unexported_tables(self.ctx.db.conn), [])
        hits = {h.kind for h in self.ctx.search.search("motion")}
        self.assertIn("course", hits)


class ImportParsingTests(TempHomeTestCase):
    def test_text_docx_and_pdf_extraction(self):
        txt = self.home / "chapters.txt"
        txt.write_text("Unit I: Algebra\nChapter 1: Real Numbers\n• Euclid's division lemma\nChapter 2: Polynomials\n",
                       encoding="utf-8")
        result = extract(txt)
        self.assertEqual(result.status, "parsed")
        docx = self.home / "syllabus.docx"
        with zipfile.ZipFile(docx, "w") as zf:
            zf.writestr("word/document.xml",
                        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
                        "<w:p><w:r><w:t>Chapter 3: Light</w:t></w:r></w:p></w:body></w:document>")
        self.assertIn("Chapter 3: Light", extract(docx).text)
        pdf = self.home / "scan.pdf"
        pdf.write_bytes(tiny_pdf(["Chapter 1: Real Numbers", "Chapter 2: Polynomials"], blank_pages=1))
        result = extract(pdf)
        self.assertIn("Real Numbers", result.text)
        self.assertEqual(result.status, "partial")
        self.assertIn("no text layer", " ".join(result.problems))
        broken = self.home / "broken.pdf"
        broken.write_bytes(b"%PDF-1.4 garbage")
        self.assertEqual(extract(broken).status, "unreadable")
        with self.assertRaises(ValueError):
            extract(self.home / "x.exe") if (self.home / "x.exe").write_bytes(b"MZ") else None

    def test_syllabus_parse_proposes_structure_with_flags(self):
        pages = ["CBSE Curriculum 2026-27\nClass X\nMathematics\nUnit I: Number Systems 06\n"
                 "Chapter 1: Real Numbers\n• Fundamental Theorem of Arithmetic\n• Fundamental Theorem of Arithmetic\n"
                 "Chapter 2: Polynomials\n", ""]
        proposal = parse(pages)
        self.assertEqual((proposal.session, proposal.authority, proposal.level), ("2026–27", "CBSE", "Class X"))
        maths = proposal.nodes[0]
        unit = maths.children[0]
        self.assertEqual((maths.kind, unit.weight), ("subject", 6.0))
        self.assertEqual([c.title for c in unit.children], ["Real Numbers", "Polynomials"])
        topics = unit.children[0].children
        self.assertTrue(topics[1].skip and "Duplicate" in topics[1].flags[0])
        self.assertTrue(any("no readable text" in f for f in proposal.flags))
        typed = from_lines("Atoms\n  Isotopes\nBonds")
        self.assertEqual([(n.title, len(n.children)) for n in typed], [("Atoms", 1), ("Bonds", 0)])

    def test_paper_and_answer_key_parsing(self):
        paper = ["Maximum Marks: 6   Time: 1 hour\nSection A consists of 2 questions of 1 mark each.\nSECTION A\n"
                 "1. Which is a prime number?\n(a) 4\n(b) 6\n(c) 7\n(d) 9\n"
                 "2. Assertion (A): Light travels in a straight line. Reason (R): It is a wave. (1)\n"
                 "SECTION B\n3. Explain why the sky is blue. (4 marks)\n"]
        proposal = parse_paper(paper)
        self.assertEqual((proposal.max_marks, proposal.duration_min), (6, 60))
        self.assertEqual([q.qtype for q in proposal.questions], ["mcq", "assertion", "la"])
        self.assertEqual(proposal.questions[2].marks, 4)
        self.assertEqual(proposal.sections[0].count, 2)
        key = parse_answer_key(["1. (c)\n2. a\n"])
        self.assertEqual(apply_answer_key(proposal, key), 2)
        self.assertEqual(proposal.questions[0].answer, "2")


if __name__ == "__main__":
    unittest.main()
