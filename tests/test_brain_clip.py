"""SecondBrain and ClipVault: data layer, privacy rules and migration 5."""

import json
import os
import unittest
from datetime import timedelta

from src.database import Database
from src.database.schema import MIGRATIONS, migrate
from src.modules.clipvault import privacy
from src.modules.clipvault.repository import expand_template, guess_kind
from src.repositories.notes import UNFILED, normalize_url
from src.services import transfer
from src.services.dates import ValidationError
from tests.helpers import FIXED_NOW, TempHomeTestCase


class MigrationFiveTests(TempHomeTestCase):
    def test_v4_notes_survive_and_gain_new_fields(self):
        path = self.home / "old.db"
        db = Database(path)
        migrate(db, MIGRATIONS[:4])
        self.assertEqual(db.user_version, 4)
        db.execute("INSERT INTO notes (title, content, tags, pinned, created_at, updated_at) "
                   "VALUES ('Old note', 'kept exactly', 'a, b', 1, '2026-01-01 09:00:00', '2026-01-02 09:00:00')")
        migrate(db, MIGRATIONS[:5])
        self.assertEqual(db.user_version, 5)
        row = dict(db.query_one("SELECT * FROM notes"))
        self.assertEqual((row["title"], row["content"], row["tags"], row["pinned"], row["updated_at"]),
                         ("Old note", "kept exactly", "a, b", 1, "2026-01-02 09:00:00"))
        self.assertEqual((row["kind"], row["format"], row["collection_id"], row["url"], row["archived"]),
                         ("note", "plain", None, "", 0))
        hits = db.query("SELECT ref_id FROM search_index WHERE search_index MATCH '\"kept\"*'")
        self.assertEqual([r[0] for r in hits], [row["id"]])
        db.close()


class SecondBrainTests(TempHomeTestCase):
    def setUp(self):
        super().setUp()
        self.brain = self.ctx.services["brain"]

    def test_kinds_collections_filters_and_search(self):
        notes = self.ctx.notes
        coll = self.brain.collections.add("Work")
        with self.assertRaises(ValidationError):
            self.brain.collections.add("work")
        a = notes.create("Deploy steps", "run the script", kind="command", collection_id=coll, language="powershell")
        b = notes.create("Docs", "", kind="bookmark", url="docs.python.org/3/")
        c = notes.create("Loose thought", "hmm")
        self.assertEqual(notes.get(b).url, "https://docs.python.org/3/")
        self.assertEqual([n.id for n in notes.list(kind="command")], [a])
        self.assertEqual([n.id for n in notes.list(collection_id=coll)], [a])
        self.assertEqual({n.id for n in notes.list(collection_id=UNFILED)}, {b, c})
        notes.update_meta(c, archived=True)
        self.assertNotIn(c, [n.id for n in notes.list()])
        self.assertIn(c, [n.id for n in notes.list(archived=None)])
        hits = self.ctx.search.search("python")
        self.assertEqual([(h.kind, h.ref_id) for h in hits], [("note", b)])
        self.assertEqual([h.ref_id for h in self.ctx.search.search("powershell")], [a])
        self.brain.collections.delete(coll)
        self.assertIsNone(notes.get(a).collection_id)
        self.assertIsNotNone(notes.get(a))  # deleting a collection never deletes notes
        with self.assertRaises(ValidationError):
            notes.update_meta(a, collection_id=coll)
        with self.assertRaises(ValidationError):
            notes.update_meta(a, kind="bogus")

    def test_urls_are_validated(self):
        self.assertEqual(normalize_url("example.com"), "https://example.com")
        self.assertEqual(normalize_url("http://localhost:8000/x"), "http://localhost:8000/x")
        for bad in ("javascript:alert(1)", "file:///C:/Windows", "not a url", "ftp://x.org", "https://"):
            with self.assertRaises(ValidationError, msg=bad):
                normalize_url(bad)
        nid, created = self.brain.add_bookmark("example.com/a", "Example")
        again, created2 = self.brain.add_bookmark("https://example.com/a")
        self.assertEqual((nid, created, created2), (again, True, False))

    def test_snippets_keep_indentation(self):
        nid = self.ctx.notes.create("Loop", "    for x in y:\n        pass\n", kind="snippet")
        self.assertEqual(self.ctx.notes.get(nid).content, "    for x in y:\n        pass")

    def test_wiki_links_and_backlinks(self):
        from src.modules.brain.service import markdown_for_preview, title_from_link, wiki_targets

        target = self.ctx.notes.create("Git tips", "rebase carefully")
        source = self.ctx.notes.create("Daily", "See [[Git tips]] and [[git tips|again]] and [[Missing]]",
                                       format="markdown")
        self.ctx.notes.create("Other", "mentions Git tips without brackets")
        self.assertEqual(wiki_targets(self.ctx.notes.get(source).content), ["Git tips", "Missing"])
        self.assertEqual([n.id for n in self.brain.backlinks(self.ctx.notes.get(target))], [source])
        self.assertEqual(self.brain.resolve("GIT TIPS").id, target)
        self.assertIsNone(self.brain.resolve("Missing"))
        md = markdown_for_preview("[[Git tips]]\n```\n[[not a link]]\n```")
        self.assertIn("(dayos-note:Git%20tips)", md)
        self.assertIn("[[not a link]]", md)
        self.assertEqual(title_from_link("dayos-note:Git%20tips"), "Git tips")
        self.assertEqual(self.brain.create_linked("Missing"), self.brain.resolve("Missing").id)

    def test_attachments_are_copies_in_the_database(self):
        nid = self.ctx.notes.create("With file")
        src = self.home / "photo.png"
        src.write_bytes(b"\x89PNG fake bytes")
        att = self.brain.attachments.add(nid, src)
        self.assertEqual(self.brain.attachments.data(att), b"\x89PNG fake bytes")
        self.assertEqual(src.read_bytes(), b"\x89PNG fake bytes")  # original untouched
        out = self.home / "out"
        first = self.brain.attachments.save_copy(att, out)
        second = self.brain.attachments.save_copy(att, out)
        self.assertNotEqual(first, second)  # never overwrites
        self.assertEqual(first.read_bytes(), b"\x89PNG fake bytes")
        big = self.home / "big.bin"
        with big.open("wb") as fh:
            fh.truncate(11 * 1024 * 1024)
        with self.assertRaises(ValidationError):
            self.brain.attachments.add(nid, big)
        self.ctx.notes.delete(nid)
        self.assertIsNone(self.brain.attachments.get(att))  # removed with its note

    def test_markdown_export_and_import_round_trip(self):
        coll = self.brain.collections.add("Recipes")
        self.ctx.notes.create("Pasta: the best?", "Boil *water*.", "food", kind="reference", collection_id=coll,
                              format="markdown")
        self.ctx.notes.create("CON", "reserved name on Windows")
        report = self.brain.export_markdown(self.paths.exports_dir)
        self.assertEqual(report.written, 2)
        files = sorted(p.relative_to(report.folder).as_posix() for p in report.folder.rglob("*.md"))
        self.assertEqual(files, ["Recipes/Pasta the best.md", "_CON.md"])
        again = self.brain.export_markdown(self.paths.exports_dir)
        self.assertNotEqual(again.folder, report.folder)
        again_import = self.brain.import_files(list(report.folder.rglob("*.md")))
        self.assertEqual(len(again_import.created), 0)  # importing the same notes twice adds nothing
        self.assertTrue(all("already in SecondBrain" in why for _n, why in again_import.skipped))
        for note in self.ctx.notes.list():
            self.ctx.notes.delete(note.id)
        before = self.ctx.notes.count()
        imported = self.brain.import_files(list(report.folder.rglob("*.md")) + [self.home / "x.pdf"])
        self.assertEqual(len(imported.created), 2)
        self.assertEqual(imported.skipped[0][0], "x.pdf")
        self.assertEqual(self.ctx.notes.count(), before + 2)
        pasta = self.ctx.notes.get(max(imported.created, key=lambda i: self.ctx.notes.get(i).title.startswith("Pasta")))
        self.assertEqual((pasta.title, pasta.kind, pasta.format, pasta.tags, pasta.content),
                         ("Pasta: the best?", "reference", "markdown", "food", "Boil *water*."))
        self.assertEqual(self.brain.collections.name_of(pasta.collection_id), "Recipes")
        plain = self.home / "plain.txt"
        plain.write_bytes("caf\xe9 notes".encode("cp1252"))
        rep = self.brain.import_files([plain])
        self.assertEqual(self.ctx.notes.get(rep.created[0]).content, "café notes")

    def test_json_export_round_trips_attachments(self):
        nid = self.ctx.notes.create("Has attachment")
        f = self.home / "a.bin"
        f.write_bytes(bytes(range(256)))
        self.brain.attachments.add(nid, f)
        out = transfer.export_json(self.paths.db_path, self.home / "export.json")
        payload = json.loads(out.read_text(encoding="utf-8"))
        self.assertIn("$base64", payload["tables"]["sb_attachments"][0]["data"])
        self.ctx.notes.delete(nid)
        transfer.import_json(self.ctx.db, out, self.paths.backups_dir)
        att = self.ctx.db.query_one("SELECT id FROM sb_attachments")
        self.assertEqual(self.brain.attachments.data(att[0]), bytes(range(256)))


class ClipVaultDataTests(TempHomeTestCase):
    def setUp(self):
        super().setUp()
        self.clips = self.ctx.services["clipvault"]

    def test_dedupe_kinds_flags_and_listing(self):
        a, created = self.clips.record("git status", "WindowsTerminal.exe")
        b, created_b = self.clips.record("git status")
        self.assertEqual((a, created, created_b), (b, True, False))
        self.assertEqual(self.clips.get(a).kind, "command")
        url, _ = self.clips.record("https://example.com/x")
        self.assertEqual(self.clips.get(url).kind, "url")
        self.clips.set_flag(url, "pinned", True)
        self.assertEqual(self.clips.list()[0].id, url)
        self.assertEqual([e.id for e in self.clips.list(view="snippets")], [a])
        tpl = self.clips.add("Hello {date}", kind="template", title="Greeting", category="Email")
        self.assertEqual([e.id for e in self.clips.list(view="templates")], [tpl])
        self.assertEqual(self.clips.categories(), ["Email"])
        self.assertEqual([e.id for e in self.clips.list("greet")], [tpl])

    def test_retention_and_clear_keep_pinned_favourites_templates_and_manual(self):
        old, _ = self.clips.record("old history")
        kept, _ = self.clips.record("pinned history")
        self.clips.set_flag(kept, "pinned", True)
        manual = self.clips.add("my snippet text")
        self.set_now(FIXED_NOW + timedelta(days=10))
        recent, _ = self.clips.record("recent history")
        removed = self.clips.enforce_retention(7, 500)
        self.assertEqual(removed, 1)
        ids = {e.id for e in self.clips.list()}
        self.assertEqual(ids, {kept, manual, recent})
        for i in range(5):
            self.clips.record(f"item {i}")
        self.clips.enforce_retention(0, 3)
        self.assertEqual(self.clips.counts()["history"], 3)
        self.clips.clear_history()
        self.assertEqual({e.id for e in self.clips.list()}, {kept, manual})
        self.clips.clear_history(everything=True)
        self.assertEqual(self.clips.list(), [])

    def test_clipboard_history_is_private_in_exports(self):
        self.clips.record("secret-ish personal text")
        self.clips.add_rule("app", "C:\\Tools\\MyVault")
        out = transfer.export_json(self.paths.db_path, self.home / "e.json")
        tables = json.loads(out.read_text(encoding="utf-8"))["tables"]
        self.assertNotIn("cv_entries", tables)
        self.assertEqual(tables["cv_rules"][0]["value"], "myvault.exe")
        self.assertNotIn("secret-ish", out.read_text(encoding="utf-8"))
        transfer.import_json(self.ctx.db, out, self.paths.backups_dir)
        self.assertEqual(len(self.clips.list()), 1)  # history untouched by an import without it
        full = transfer.export_json(self.paths.db_path, self.home / "f.json", include_private=True)
        self.assertIn("cv_entries", json.loads(full.read_text(encoding="utf-8"))["tables"])
        # never in the search index
        self.assertEqual(self.ctx.search.search("personal"), [])

    def test_templates_and_kind_guessing(self):
        from datetime import datetime

        text = expand_template("On {date} at {time}: {clipboard} {unknown}", "pasted", datetime(2026, 1, 2, 3, 4))
        self.assertEqual(text, "On 2026-01-02 at 03:04: pasted {unknown}")
        self.assertEqual(guess_kind("def f():\n    return 1"), "code")
        self.assertEqual(guess_kind("Get-ChildItem -Recurse"), "command")
        self.assertEqual(guess_kind("Just a sentence."), "text")


class PrivacyTests(unittest.TestCase):
    def decide(self, text, app="", formats=frozenset(), rules=(), **kw):
        opts = dict(max_chars=20000, skip_sensitive=True, skip_private_apps=True)
        opts.update(kw)
        return privacy.decide(text, app, set(formats), list(rules), **opts)

    def test_private_apps_and_formats_are_skipped(self):
        self.assertFalse(self.decide("hunter2", app="KeePassXC.exe").keep)
        self.assertFalse(self.decide("anything", formats={"ExcludeClipboardContentFromMonitorProcessing"}).keep)
        self.assertTrue(self.decide("anything", app="KeePassXC.exe", skip_private_apps=False).keep)
        self.assertTrue(self.decide("ordinary words", app="notepad.exe").keep)

    def test_sensitive_patterns(self):
        for text in ("ghp_" + "a" * 36, "-----BEGIN RSA PRIVATE KEY-----\nabc", "password: hunter2",
                     "123456", "123 456", "4111 1111 1111 1111", "AKIA" + "A" * 16,
                     "eyJhbGciOiJIUzI1.eyJzdWIiOiIxMjM0.SflKxwRJSMeKKF2QT4"):
            self.assertFalse(self.decide(text).keep, text)
        for text in ("2026", "4111 1111 1111 1112", "call me at 5", "def password_field(): pass"):
            self.assertTrue(self.decide(text).keep, text)
        self.assertTrue(self.decide("123456", skip_sensitive=False).keep)

    def test_rules_and_limits(self):
        rules = [privacy.Rule("contains", "internal-only"), privacy.Rule("pattern", r"^TICKET-\d+$"),
                 privacy.Rule("app", "slack.exe"), privacy.Rule("contains", "off", enabled=False)]
        self.assertFalse(self.decide("this is INTERNAL-ONLY text", rules=rules).keep)
        self.assertFalse(self.decide("TICKET-42", rules=rules).keep)
        self.assertFalse(self.decide("hello", app="Slack.exe", rules=rules).keep)
        self.assertTrue(self.decide("turn it off", rules=rules).keep)
        self.assertFalse(self.decide("x" * 21, max_chars=20).keep)
        self.assertEqual(self.decide("   ").reason, "empty")
        with self.assertRaises(ValueError):
            privacy.validate_rule("pattern", "([")
        self.assertEqual(privacy.validate_rule("app", "C:\\Program Files\\Foo\\Bar"), "bar.exe")

    def test_reasons_never_contain_the_text(self):
        secret = "password: correct-horse-battery"
        reason = self.decide(secret).reason
        self.assertNotIn("correct-horse", reason)


if __name__ == "__main__":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    unittest.main()
