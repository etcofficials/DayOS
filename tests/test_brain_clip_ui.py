"""SecondBrain and ClipVault driven through the real widgets (offscreen)."""

import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer, QUrl  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from src.ui.theme import theme  # noqa: E402
from tests.helpers import TempHomeTestCase  # noqa: E402

app = QApplication.instance() or QApplication([])


def pump(ms: int = 30) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


class WindowTestCase(TempHomeTestCase):
    def setUp(self):
        super().setUp()
        from src.ui.main_window import MainWindow

        theme.set_asset_dir(self.paths.cache_dir)
        theme.apply("paper")
        self.ctx.settings.set("capture.global", False)
        self.window = MainWindow(self.ctx)
        self.window.resize(1300, 860)
        self.window.show()
        pump(30)

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        pump(20)
        super().tearDown()


class SecondBrainUiTests(WindowTestCase):
    def setUp(self):
        super().setUp()
        self.window.navigate("notes")
        self.page = self.window.page("notes")
        self.brain = self.ctx.services["brain"]

    def test_snippet_and_bookmark_kinds(self):
        self.page.new_item("snippet")
        self.assertTrue(self.page.lang_edit.isVisibleTo(self.page))
        self.assertTrue(self.page.editor.font().fixedPitch() or "mono" in self.page.editor.font().family().lower()
                        or self.page.editor.font().family() != self.page._default_font.family())
        self.page.title_edit.setText("List files")
        self.page.title_edit.textEdited.emit("List files")
        self.page.editor.setPlainText("    Get-ChildItem -Recurse")
        self.page.save_now()
        note = self.ctx.notes.get(self.page.current.id)
        self.assertEqual((note.kind, note.format, note.content), ("snippet", "plain", "    Get-ChildItem -Recurse"))
        self.page.new_item("bookmark")
        self.assertTrue(self.page.url_row.isVisibleTo(self.page))
        self.page.url_edit.setText("docs.python.org")
        self.page._url_finished()
        self.assertEqual(self.ctx.notes.get(self.page.current.id).url, "https://docs.python.org")
        with mock.patch("src.modules.brain.ui.page.show_error") as err:
            self.page.url_edit.setText("javascript:alert(1)")
            self.page._url_finished()
            err.assert_called_once()
        self.assertEqual(self.ctx.notes.get(self.page.current.id).url, "https://docs.python.org")

    def test_untouched_template_note_is_discarded(self):
        self.page.new_item("troubleshooting")
        self.assertIn("## Problem", self.page.editor.toPlainText())
        self.window.navigate("today")
        app.processEvents()
        self.assertEqual(self.ctx.notes.count(), 0)

    def test_kind_and_collection_changes_and_archive(self):
        coll = self.brain.collections.add("Linux")
        self.page.refresh()
        self.page.new_item()
        self.page.title_edit.setText("SSH keys")
        self.page.title_edit.textEdited.emit("SSH keys")
        self.page.save_now()
        nid = self.page.current.id
        self.page.kind_combo.setCurrentIndex(self.page.kind_combo.findData("reference"))
        self.page.kind_combo.activated.emit(self.page.kind_combo.currentIndex())
        self.page.coll_combo.setCurrentIndex(self.page.coll_combo.findData(coll))
        self.page.coll_combo.activated.emit(self.page.coll_combo.currentIndex())
        note = self.ctx.notes.get(nid)
        self.assertEqual((note.kind, note.collection_id), ("reference", coll))
        self.page._toggle_archive()
        self.assertEqual(self.ctx.notes.get(nid).archived, 1)
        listed = [self.page.list.item(i).data(0x0100) for i in range(self.page.list.count())]
        self.assertNotIn(nid, listed)
        self.page.show_archived.setChecked(True)
        listed = [self.page.list.item(i).data(0x0100) for i in range(self.page.list.count())]
        self.assertIn(nid, listed)

    def test_markdown_preview_and_wiki_links(self):
        target = self.ctx.notes.create("Git tips", "rebase")
        self.page.refresh()
        self.page.new_item()
        self.page.title_edit.setText("Daily")
        self.page.title_edit.textEdited.emit("Daily")
        self.page.editor.setPlainText("# Hi\nSee [[Git tips]] and [[Brand new]]")
        self.page.format_combo.setCurrentIndex(self.page.format_combo.findData("markdown"))
        self.page.format_combo.activated.emit(self.page.format_combo.currentIndex())
        self.page.toggle_preview()
        self.assertIs(self.page.body.currentWidget(), self.page.preview)
        self.assertIn("Git tips", self.page.preview.toPlainText())
        source = self.page.current.id
        self.page._on_link(QUrl("dayos-note:Git%20tips"))
        self.assertEqual(self.page.current.id, target)
        self.assertEqual([n.id for n in self.brain.backlinks(self.ctx.notes.get(target))], [source])
        with mock.patch("src.modules.brain.ui.page.confirm", return_value=True):
            self.page._on_link(QUrl("dayos-note:Brand%20new"))
        self.assertEqual(self.page.current.title, "Brand new")
        # remote resources are never loaded by the preview
        self.assertIsNone(self.page.preview.loadResource(2, QUrl("https://example.com/x.png")))

    def test_attachments_and_import_export(self):
        self.page.new_item()
        self.page.title_edit.setText("Holiday")
        self.page.title_edit.textEdited.emit("Holiday")
        f = self.home / "plan.txt"
        f.write_text("itinerary", encoding="utf-8")
        self.page.attach_file(str(f))
        self.assertEqual([a.filename for a in self.brain.attachments.list(self.page.current.id)], ["plan.txt"])
        self.page.export_markdown(None)
        folders = list(self.paths.exports_dir.glob("secondbrain-*"))
        self.assertEqual(len(folders), 1)
        md = self.home / "imported.md"
        md.write_text("---\ntitle: From disk\nkind: idea\n---\nGreat plan", encoding="utf-8")
        self.page.import_files([str(md)])
        self.assertEqual((self.page.current.title, self.page.current.kind), ("From disk", "idea"))


class ClipVaultUiTests(WindowTestCase):
    def setUp(self):
        super().setUp()
        self.monitor = self.window.clip_monitor
        self.monitor.probe = lambda: (set(), "notepad.exe", False)
        self.repo = self.ctx.services["clipvault"]
        self.clipboard = QApplication.clipboard()

    def copy(self, text: str) -> None:
        self.clipboard.setText(text)
        pump(10)

    def test_nothing_is_read_until_turned_on(self):
        self.copy("before consent")
        self.assertEqual(self.repo.list(), [])
        self.assertFalse(self.window.clip_button.isVisibleTo(self.window))
        self.window.navigate("clipvault")
        page = self.window.page("clipvault")
        self.assertTrue(page.setup.isVisibleTo(page))
        page.setup_hotkey.setChecked(False)
        page.turn_on()
        self.assertTrue(self.ctx.settings.get("clip.enabled"))
        self.assertFalse(page.setup.isVisibleTo(page))
        self.assertTrue(self.window.clip_button.isVisibleTo(self.window))
        self.copy("after consent")
        self.assertEqual([e.content for e in self.repo.list()], ["after consent"])
        self.assertEqual(self.repo.list()[0].source_app, "notepad.exe")

    def test_skips_secrets_pause_and_copy_back(self):
        self.ctx.settings.set("clip.enabled", True)
        self.copy("password: hunter2")
        self.assertIn("password", self.monitor.last_skip)
        self.assertNotIn("hunter2", self.monitor.last_skip)
        self.copy("ghp_" + "x" * 36)
        self.assertIn("token", self.monitor.last_skip)
        self.assertEqual(self.repo.list(), [])
        self.monitor.probe = lambda: ({"ExcludeClipboardContentFromMonitorProcessing"}, "KeePassXC.exe", False)
        self.copy("from the password manager")
        self.assertEqual(self.repo.list(), [])
        self.monitor.probe = lambda: (set(), "code.exe", False)
        self.copy("git status")
        self.window.clip_button.click()  # sidebar pause
        self.assertTrue(self.ctx.settings.get("clip.paused"))
        self.copy("while paused")
        self.assertEqual([e.content for e in self.repo.list()], ["git status"])
        self.window.clip_button.click()
        self.assertFalse(self.ctx.settings.get("clip.paused"))
        entry = self.repo.list()[0]
        self.assertEqual(self.monitor.copy_entry(entry.id), "git status")
        pump(10)
        self.assertEqual(self.clipboard.text(), "git status")
        self.assertEqual(len(self.repo.list()), 1)
        self.assertEqual(self.repo.get(entry.id).use_count, 1)

    def test_templates_picker_and_page_actions(self):
        from src.modules.clipvault.ui.page import ClipEntryDialog
        from src.modules.clipvault.ui.picker import ClipPicker

        self.window.navigate("clipvault")
        page = self.window.page("clipvault")
        dlg = ClipEntryDialog(self.repo, "template", page)
        dlg.title.setText("Sign-off")
        dlg.text.setPlainText("Thanks! {date}")
        dlg._on_save()
        self.assertIsNotNone(dlg.saved_id)
        page.select_entry(dlg.saved_id)
        self.assertEqual(page.current_id, dlg.saved_id)
        page.copy_current()
        self.assertTrue(self.clipboard.text().startswith("Thanks! 2026-09-27"))
        picker = ClipPicker.open(self.window, 0)
        self.assertGreater(picker.list.count(), 0)
        picker.search.setText("sign")
        self.assertEqual(picker.list.count(), 1)
        picker.copy_selected()
        pump(200)
        self.assertIsNone(ClipPicker._instance)  # closed (and deleted) after copying
        page.save_to_brain()
        self.assertEqual(self.ctx.notes.list()[0].title, "Sign-off")
        with mock.patch("src.modules.clipvault.ui.page.confirm", return_value=True):
            page.delete_current()
        self.assertEqual(self.repo.list(), [])

    def test_palette_search_only_when_allowed_and_settings_section(self):
        self.repo.add("unique-marker text", kind="text")
        self.assertEqual([h for h in self.ctx.search.search("marker") if h.kind == "clip"], [])
        self.ctx.settings.set("clip.search_in_palette", True)
        self.assertEqual([h.kind for h in self.ctx.search.search("marker")], ["clip"])
        self.window.navigate("settings")
        settings = self.window.page("settings")
        settings.show_section("clipvault", animate=False)
        settings.show_section("secondbrain", animate=False)
        self.assertIn("clipvault", settings._built)
        self.assertIn("secondbrain", settings._built)

    def test_hotkey_source_registers_only_when_enabled(self):
        self.assertFalse(self.window.hotkeys.is_registered("clipvault"))
        self.assertIn("clipvault", self.window.hotkey_sources)
        seq, _handler = self.window.hotkey_sources["clipvault"]
        self.assertIsNone(seq())
        # never claim a real system-wide shortcut from a test
        with mock.patch.object(self.window.hotkeys, "register", return_value=True) as register:
            self.ctx.settings.set("clip.global", True)
        self.assertEqual(seq(), "Ctrl+Alt+Shift+V")
        register.assert_any_call("clipvault", "Ctrl+Alt+Shift+V")


if __name__ == "__main__":
    unittest.main()
