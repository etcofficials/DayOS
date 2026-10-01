"""Optional AI: off by default, consent before sending, validation of results (no real API calls)."""

import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from src.services import ai  # noqa: E402
from tests.helpers import TempHomeTestCase  # noqa: E402

app = QApplication.instance() or QApplication([])


def pump(ms: int = 30) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


class FakeProvider(ai.Provider):
    def __init__(self, response: dict) -> None:
        self.response = response
        self.calls: list[dict] = []

    def generate_json(self, **kwargs) -> dict:
        self.calls.append(kwargs)
        return self.response


GOOD_QUESTIONS = {"questions": [
    {"qtype": "mcq", "text": "Which organelle makes ATP?", "options": ["Nucleus", "Mitochondrion", "Ribosome", "Wall"],
     "answer": "1", "explanation": "Mitochondria carry out respiration.", "marks": 1},
    {"qtype": "mcq", "text": "Bad: three options only?", "options": ["a", "b", "c"], "answer": "0",
     "explanation": "", "marks": 1},
    {"qtype": "tf", "text": "Plant cells have a cell wall.", "options": [], "answer": "TRUE", "explanation": "",
     "marks": 1},
    {"qtype": "sa", "text": "Explain osmosis briefly.", "options": [], "answer": "Movement of water across a "
     "semi-permeable membrane.", "explanation": "", "marks": 2},
    {"qtype": "sa", "text": "Wrong marks", "options": [], "answer": "x", "explanation": "", "marks": 9},
    {"qtype": "essay", "text": "Unknown type", "options": [], "answer": "x", "explanation": "", "marks": 1},
]}


class AiServiceTests(TempHomeTestCase):
    def test_off_by_default_and_requires_a_saved_key(self):
        self.assertIsNone(ai.config_from_settings(self.ctx.settings))
        with self.assertRaises(ai.AIError) as err:
            ai.provider_for(self.ctx.settings)
        self.assertEqual(err.exception.kind, "not_configured")
        self.ctx.settings.set("ai.provider", "anthropic")
        with mock.patch("src.services.credentials.load", return_value=None):
            with self.assertRaises(ai.AIError):
                ai.provider_for(self.ctx.settings)
        with mock.patch("src.services.credentials.load", return_value="sk-test"):
            provider = ai.provider_for(self.ctx.settings)
        self.assertEqual(provider.model, "claude-opus-5-5")
        with self.assertRaises(KeyError):
            self.ctx.settings.set("ai.api_key", "sk-x")  # keys are never settings
        self.assertNotIn("ai.api_key", [r[0] for r in self.ctx.db.query("SELECT key FROM settings")])

    def test_question_results_are_validated(self):
        fake = FakeProvider(GOOD_QUESTIONS)
        questions = ai.generate_questions(fake, "Biology > Cells", 5)
        self.assertEqual([q["qtype"] for q in questions], ["mcq", "tf", "sa"])
        self.assertEqual(questions[1]["answer"], "true")
        self.assertEqual(fake.calls[0]["content"], ai.questions_payload("Biology > Cells", 5))
        tasks = ai.suggest_tasks(FakeProvider({"tasks": [{"title": "  Write   tests ", "minutes": 9999},
                                                         {"title": "", "minutes": 10}]}), "App", "", [])
        self.assertEqual(tasks, [("Write tests", 480)])
        summary, tags = ai.summarize_note(FakeProvider({"summary": "Short.", "tags": ["#Bio", "cells"]}), "T", "body")
        self.assertEqual((summary, tags), ("Short.", ["Bio", "cells"]))
        with self.assertRaises(ai.AIError):
            ai.summarize_note(FakeProvider({"summary": "", "tags": []}), "T", "body")
        with self.assertRaises(ai.AIError) as err:
            ai.summarize_note(FakeProvider({}), "T", "x" * (ai.MAX_INPUT_CHARS + 1))
        self.assertEqual(err.exception.kind, "too_long")

    def test_anthropic_request_shape_and_refusal(self):
        captured = {}

        class Resp:
            stop_reason = "end_turn"
            content = [type("B", (), {"type": "text", "text": '{"ok": true}'})()]

        class FakeMessages:
            def create(self, **kwargs):
                captured.update(kwargs)
                return Resp()

        fake_client = type("C", (), {"beta": type("Beta", (), {"messages": FakeMessages()})()})()
        provider = ai.AnthropicProvider("sk-test", "claude-opus-5-5")
        import anthropic

        with mock.patch.object(ai.AnthropicProvider, "_client", return_value=(anthropic, fake_client)):
            provider.check()
            self.assertEqual(captured["model"], "claude-opus-5-5")
            self.assertEqual(captured["fallbacks"], "default")
            self.assertEqual(captured["betas"], [ai.FALLBACK_BETA])
            self.assertEqual(captured["output_config"]["format"]["type"], "json_schema")
            self.assertNotIn("thinking", captured)  # adaptive thinking by default on this model
            Resp.stop_reason = "refusal"
            with self.assertRaises(ai.AIError) as err:
                provider.check()
            self.assertEqual(err.exception.kind, "refused")
        haiku = ai.AnthropicProvider("sk-test", "claude-haiku-4-5")
        Resp.stop_reason = "end_turn"
        captured.clear()
        with mock.patch.object(ai.AnthropicProvider, "_client", return_value=(anthropic, fake_client)):
            haiku.check()
        self.assertNotIn("fallbacks", captured)


class AiUiTests(TempHomeTestCase):
    def setUp(self):
        super().setUp()
        from src.ui.main_window import MainWindow
        from src.ui.theme import theme

        theme.set_asset_dir(self.paths.cache_dir)
        theme.apply("paper")
        self.ctx.settings.set("capture.global", False)
        self.window = MainWindow(self.ctx)
        self.window.show()
        pump(20)

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        pump(20)
        super().tearDown()

    def test_nothing_is_sent_without_setup_or_consent(self):
        from src.ui import ai_consent

        self.window.navigate("notes")
        page = self.window.page("notes")
        nid = self.ctx.notes.create("Private", "my private thoughts")
        page.open_note(nid)
        work = mock.Mock()
        with mock.patch("src.ui.ai_consent.show_info") as info:
            self.assertFalse(ai_consent.run_ai(page, self.ctx.settings, "test", "x", work, lambda r: None))
            info.assert_called_once()
        self.ctx.settings.set("ai.provider", "anthropic")
        with mock.patch("src.services.ai.is_configured", return_value=True), \
                mock.patch.object(ai_consent.ConsentDialog, "exec", return_value=0):
            self.assertFalse(ai_consent.run_ai(page, self.ctx.settings, "test", "x", work, lambda r: None))
        work.assert_not_called()

    def test_note_summary_flow_after_consent(self):
        self.window.navigate("notes")
        page = self.window.page("notes")
        nid = self.ctx.notes.create("Cells", "Cells are the basic unit of life.", format="markdown")
        page.open_note(nid)
        self.ctx.settings.set("ai.provider", "anthropic")
        fake = FakeProvider({"summary": "Cells are life's building blocks.", "tags": ["biology"]})
        shown = {}

        def consent_exec(dialog):
            shown["text"] = dialog.findChildren(__import__("PySide6.QtWidgets", fromlist=["QPlainTextEdit"])
                                                .QPlainTextEdit)[0].toPlainText()
            return 1

        from src.ui.ai_consent import ConsentDialog, ReviewDialog

        with mock.patch("src.services.ai.is_configured", return_value=True), \
                mock.patch("src.services.ai.provider_for", return_value=fake), \
                mock.patch.object(ConsentDialog, "exec", consent_exec), \
                mock.patch.object(ReviewDialog, "exec", return_value=1):
            page.ai_summarize()
            for _ in range(100):
                pump(20)
                if "AI summary" in self.ctx.notes.get(nid).content:
                    break
        self.assertEqual(shown["text"], ai.note_payload("Cells", "Cells are the basic unit of life."))
        note = self.ctx.notes.get(nid)
        self.assertTrue(note.content.startswith("> **AI summary:** Cells are life's building blocks."))
        self.assertIn("biology", note.tags)

    def test_ai_settings_section_builds_without_a_key(self):
        self.window.navigate("settings")
        settings = self.window.page("settings")
        settings.show_section("ai", animate=False)
        self.assertIn("ai", settings._built)


if __name__ == "__main__":
    unittest.main()
