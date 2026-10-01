"""Focus sessions linked to StudyForge course topics."""

import os
import unittest
from datetime import timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from src.repositories.study import new_session_uid  # noqa: E402
from tests.helpers import FIXED_NOW, TempHomeTestCase  # noqa: E402

app = QApplication.instance() or QApplication([])


def pump(ms: int = 20) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


class FocusTopicTests(TempHomeTestCase):
    def test_session_records_course_topic(self):
        from src.ui.main_window import MainWindow
        from src.ui.theme import theme

        sf = self.ctx.services["studyforge"]
        cid = sf.courses.create("Physics")
        node = sf.courses.add_node(cid, "chapter", "Light")
        theme.set_asset_dir(self.paths.cache_dir)
        theme.apply("paper")
        self.ctx.settings.set("capture.global", False)
        window = MainWindow(self.ctx)
        try:
            window.navigate("study")
            page = window.page("study")
            page.refresh()
            self.assertTrue(page.topic_combo.isVisibleTo(page))
            page.link_topic(node)
            self.assertEqual(page.topic_combo.current_id(), node)
            uid = new_session_uid()
            self.assertTrue(self.ctx.study.record(session_uid=uid, subject_id=None, started_at=FIXED_NOW,
                                                  actual_seconds=1500, node_id=page._existing_node(node)))
            self.assertEqual(self.ctx.db.scalar("SELECT node_id FROM study_sessions WHERE session_uid = ?", (uid,)),
                             node)
            self.assertIsNone(page._existing_node(999999))  # a deleted topic is never stored
        finally:
            window.close()
            window.deleteLater()
            pump()


if __name__ == "__main__":
    unittest.main()
