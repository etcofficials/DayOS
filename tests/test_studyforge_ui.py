"""StudyForge UI flows driven through the real widgets (offscreen)."""

import os
import unittest
from datetime import timedelta
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QCheckBox, QLabel, QRadioButton  # noqa: E402

from src.ui.theme import theme  # noqa: E402
from tests.helpers import FIXED_NOW, TempHomeTestCase  # noqa: E402

app = QApplication.instance() or QApplication([])
TODAY = FIXED_NOW.date()


def pump(ms: int = 30) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


class StudyForgeUiTests(TempHomeTestCase):
    def setUp(self):
        super().setUp()
        from src.ui.main_window import MainWindow

        theme.set_asset_dir(self.paths.cache_dir)
        theme.apply("paper")
        self.ctx.settings.set("capture.global", False)
        self.window = MainWindow(self.ctx)
        self.window.resize(1300, 860)
        self.window.show()
        self.window.navigate("studyforge")
        self.page = self.window.page("studyforge")
        self.sf = self.ctx.services["studyforge"]
        pump(40)

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        pump(20)
        super().tearDown()

    def _course(self):
        from src.modules.studyforge.ui.page import CourseDialog

        dlg = CourseDialog(self.page)
        dlg.name.setText("Biology")
        dlg._on_save()
        self.page.select_course(dlg.saved_id)
        cid = dlg.saved_id
        ch = self.sf.courses.add_node(cid, "chapter", "Cells")
        return cid, ch

    def test_empty_state_then_cbse_setup(self):
        self.page.refresh()
        self.assertFalse(self.page.tabs.isVisibleTo(self.page))
        from src.modules.studyforge.ui.importer import CbseSetupDialog

        dlg = CbseSetupDialog(self.page)
        dlg.session.setText("2026–27")
        dlg.dates["Science"].set_value(TODAY + timedelta(days=60))
        dlg._on_save()
        self.assertFalse(dlg.error.isVisibleTo(dlg))
        self.page.select_course(dlg.course_id)
        self.assertTrue(self.page.tabs.isVisibleTo(self.page))
        for i in range(self.page.tabs.count()):
            self.page.tabs.setCurrentIndex(i)
            pump(10)
        tree = self.page.tab_widgets[1].tree
        self.assertGreater(tree.topLevelItemCount(), 2)

    def test_question_dialog_test_creation_taking_and_marking(self):
        from src.modules.studyforge.ui.bank import QuestionDialog
        from src.modules.studyforge.ui.take import ResultsDialog, TakeTestDialog
        from src.modules.studyforge.ui.tests_tab import CreateTestDialog

        cid, ch = self._course()
        dlg = QuestionDialog(self.ctx, cid, self.page, default_node=ch)
        dlg.text.setPlainText("Which organelle makes ATP?")
        dlg.options_edit.setPlainText("Nucleus\nMitochondrion\nRibosome")
        dlg.choice_buttons[1].setChecked(True)
        dlg._on_save()
        self.assertFalse(dlg.error.isVisibleTo(dlg))
        written = QuestionDialog(self.ctx, cid, self.page, default_node=ch)
        written.qtype.setCurrentIndex(written.qtype.findData("sa"))
        written.text.setPlainText("Describe the cell membrane.")
        written.marks.setValue(2)
        written.rubric.add_row("semi-permeable", 1)
        written.rubric.add_row("phospholipid bilayer", 1)
        written._on_save()
        self.assertFalse(written.error.isVisibleTo(written))
        create = CreateTestDialog(self.page, [ch], "custom")
        for t, cb in create.type_checks.items():
            cb.setChecked(t in ("mcq", "sa"))
        create.count.setValue(2)
        create.timed.setChecked(False)
        create._on_save()
        self.assertFalse(create.error.isVisibleTo(create))
        test_id = create.test_id
        self.assertIsNotNone(test_id)
        take = TakeTestDialog(self.page, test_id)
        for i, item in enumerate(take.items):
            take.go(i)
            if item.question["qtype"] == "mcq":
                radios = take.editor.findChildren(QRadioButton)
                radios[1].setChecked(True)
            else:
                take._changed("It is a semi-permeable layer.")
        take.save_current()
        with mock.patch("src.modules.studyforge.ui.take.confirm", return_value=True), \
                mock.patch.object(self.page, "show_attempt") as shown:
            take.submit()
            shown.assert_called_once()
        attempt_id = shown.call_args[0][0]
        attempt = self.sf.tests.attempt(attempt_id)
        self.assertEqual((attempt.status, attempt.score), ("submitted", 1.0))
        results = ResultsDialog(self.page, attempt_id)
        boxes = results.findChildren(QCheckBox)
        boxes[0].setChecked(True)  # semi-permeable point
        item = next(it for it in self.sf.tests.items(test_id) if it.question["qtype"] == "sa")
        results._save_mark(item.id, 1.0, "")
        self.assertEqual(self.sf.tests.attempt(attempt_id).status, "marked")
        self.assertEqual(self.sf.tests.attempt(attempt_id).score, 2.0)
        for tab in (3, 4, 5, 7):
            self.page.tabs.setCurrentIndex(tab)
            pump(10)

    def test_leaving_a_test_keeps_answers_for_resume(self):
        from src.modules.studyforge.ui.take import TakeTestDialog

        cid, ch = self._course()
        self.sf.bank.add(cid, "tf", "Cells divide.", node_id=ch, answer="true")
        res = self.ctx.services["studyforge.service"].generate(
            __import__("src.modules.studyforge.service", fromlist=["GenerateRequest"]).GenerateRequest(
                cid, "Resume me", [ch], sections=[__import__("src.modules.studyforge.models",
                                                             fromlist=["Section"]).Section("A", "tf", 1, 1)]))
        take = TakeTestDialog(self.page, res.test_id)
        take._changed("true")
        with mock.patch("src.modules.studyforge.ui.take.confirm", return_value=True):
            take.reject()
        again = TakeTestDialog(self.page, res.test_id)
        self.assertEqual(again.attempt_id, take.attempt_id)
        self.assertEqual(again._response(again.items[0].id), "true")
        self.assertEqual(len(self.ctx.services["studyforge.service"].unfinished()), 1)

    def test_import_wizard_reviews_before_saving(self):
        from src.modules.studyforge import extract
        from src.modules.studyforge.ui.importer import ImportWizard

        cid, _ = self._course()
        doc = self.home / "syllabus.txt"
        doc.write_text("Biology 2026-27\nChapter 1: Cell Structure\n• Organelles\nChapter 2: Tissues\n", encoding="utf-8")
        wiz = ImportWizard(self.page)
        wiz.path = doc
        wiz.result = extract.extract(doc)
        wiz._describe()
        wiz.kind.setCurrentIndex(wiz.kind.findData("syllabus"))
        wiz.analyse()
        subject = wiz.tree.topLevelItem(0)
        self.assertEqual((wiz.tree.topLevelItemCount(), subject.text(0), subject.childCount()), (1, "Biology", 2))
        self.assertEqual(len(self.sf.courses.documents(cid)), 0)  # nothing saved yet
        subject.child(1).setCheckState(0, subject.child(1).checkState(0).Unchecked)
        wiz.target.setCurrentIndex(wiz.target.findData(cid))
        wiz.save_map()
        titles = [n.title for n in self.sf.courses.nodes(cid)]
        self.assertIn("Cell Structure", titles)
        self.assertNotIn("Tissues", titles)
        self.assertEqual(len(self.sf.courses.documents(cid)), 1)

    def test_today_shows_studyforge_revision(self):
        cid, ch = self._course()
        self.sf.courses.update_node(ch, exam_date=TODAY + timedelta(days=5))
        today = self.window.page("today")
        self.ctx.settings.set("dashboard.widgets", ["revision"])
        today.refresh()
        texts = " ".join(w.text() for w in today.revision_card.findChildren(QLabel))
        self.assertIn("StudyForge topic", texts)
        self.assertIn("Cells", texts)

    def test_palette_opens_studyforge_records(self):
        cid, ch = self._course()
        qid = self.sf.bank.add(cid, "tf", "Mitochondria have their own DNA.", node_id=ch, answer="true")
        hits = self.ctx.search.search("mitochondria")
        self.assertEqual([(h.kind, h.ref_id) for h in hits], [("question", qid)])
        self.assertTrue(self.window.openers.can_open("question"))
        self.assertIsNotNone(self.window.commands.get("studyforge.test"))


if __name__ == "__main__":
    unittest.main()
