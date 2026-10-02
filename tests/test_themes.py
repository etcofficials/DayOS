"""DayOS v2 design system: five themes, contrast, live switching, persistence, art and navigation."""

import json
import os
import sqlite3
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from src.config import resource_root  # noqa: E402
from src.modules import registry  # noqa: E402
from src.ui.theme import FONT_SCALES, build_stylesheet, theme  # noqa: E402
from src.ui.theme_settings import apply_from_settings, set_accent, watch_settings  # noqa: E402
from src.ui.themes import THEME_IDS, THEMES, contrast, get_theme  # noqa: E402
from tests.helpers import TempHomeTestCase  # noqa: E402

app = QApplication.instance() or QApplication([])

TEXT_TOKENS = ("text", "text2", "text3", "accent_text", "blue_text", "terracotta_text", "amber_text", "danger")
BACKGROUNDS = ("surface", "bg", "elevated", "sidebar")
PAIRS = [("on_primary", "primary", 4.5), ("on_accent", "accent", 3.0), ("on_segment_active", "segment_active", 4.5),
         ("nav_active", "nav_pill", 4.5), ("accent_text", "accent_soft", 4.5), ("danger", "danger_soft", 4.5),
         ("blue_text", "blue_soft", 4.5), ("terracotta_text", "terracotta_soft", 4.5),
         ("amber_text", "amber_soft", 4.5), ("text", "selection", 4.5), ("text", "hover", 4.5)]


class ThemeRegistryTests(unittest.TestCase):
    def test_five_themes_with_distinct_identities(self):
        self.assertEqual(THEME_IDS, ("paper", "midnight", "zen", "aurora", "espresso"))
        self.assertEqual(len({t.name for t in THEMES.values()}), 5)
        self.assertEqual({t.mode for t in THEMES.values()}, {"light", "dark"})
        self.assertEqual(len({THEMES[t].palette()["bg"] for t in THEME_IDS}), 5)

    def test_every_theme_defines_the_same_token_set(self):
        keys = set(THEMES["paper"].palette())
        for t in THEMES.values():
            for accent in [None] + [a.key for a in t.accents]:
                self.assertEqual(set(t.palette(accent)), keys, f"{t.id}/{accent}")

    def test_specified_initial_colours(self):
        paper, midnight = THEMES["paper"].palette(), THEMES["midnight"].palette()
        self.assertEqual((paper["bg"], paper["sidebar"], paper["surface"], paper["elevated"]),
                         ("#F5F2E9", "#E9EDE3", "#FFFDF7", "#F0F1E8"))
        self.assertEqual((paper["accent"], paper["accent_dark"], paper["accent_soft"], paper["divider"]),
                         ("#71896C", "#425845", "#DCE4D5", "#E1E2D8"))
        self.assertEqual((paper["terracotta"], paper["blue"], paper["text"]), ("#C77D59", "#7793AE", "#252C26"))
        self.assertEqual((midnight["bg"], midnight["sidebar"], midnight["surface"], midnight["elevated"]),
                         ("#191D1A", "#202621", "#272E28", "#303830"))
        self.assertEqual((midnight["text"], midnight["text2"], midnight["accent"], midnight["accent_dark"],
                          midnight["accent_soft"], midnight["divider"]),
                         ("#EAEDE5", "#ADB6A9", "#A6BE9B", "#829A79", "#39483A", "#3A443B"))

    def test_readable_contrast_in_every_theme_and_accent(self):
        for t in THEMES.values():
            for accent in [None] + [a.key for a in t.accents]:
                p = t.palette(accent)
                for bg in BACKGROUNDS:
                    for fg in TEXT_TOKENS:
                        self.assertGreaterEqual(contrast(p[fg], p[bg]), 4.5, f"{t.id}/{accent}: {fg} on {bg}")
                for fg, bg, minimum in PAIRS:
                    self.assertGreaterEqual(contrast(p[fg], p[bg]), minimum, f"{t.id}/{accent}: {fg} on {bg}")

    def test_legacy_names_and_unknown_ids_resolve_safely(self):
        self.assertEqual(get_theme("light").id, "paper")
        self.assertEqual(get_theme("dark").id, "midnight")
        self.assertEqual(get_theme("neon").id, "paper")
        self.assertEqual(get_theme(None).id, "paper")

    def test_theme_artwork_exists(self):
        art = resource_root() / "assets" / "art"
        for t in THEMES.values():
            for variant in t.art_variants.values():
                self.assertTrue((art / f"{variant}.svg").is_file(), variant)

    def test_stylesheet_uses_theme_tokens_and_scale(self):
        t = THEMES["espresso"]
        css = build_stylesheet(t.palette(), {}, t, 1.25)
        self.assertIn(t.palette()["bg"], css)
        self.assertIn("13.12pt", css)  # 10.5pt body text at 125%
        self.assertNotIn("#F5F2E9", css)  # no Paper colours leak into Espresso


class ThemeRuntimeTests(TempHomeTestCase):
    def setUp(self):
        super().setUp()
        theme.set_asset_dir(self.paths.cache_dir)
        apply_from_settings(self.ctx.settings)
        watch_settings(self.ctx.settings)

    def tearDown(self):
        theme.apply("paper", accent=None, scale=1.0)
        super().tearDown()

    def test_switching_is_live_and_never_touches_records(self):
        self.ctx.tasks.create("Keep me")
        self.ctx.notes.create("Note", "body")
        before = self.ctx.db.query("SELECT * FROM tasks")
        seen = []
        theme.changed.connect(lambda: seen.append(theme.id))
        for tid in THEME_IDS:
            self.ctx.settings.set("theme", tid)
            self.assertEqual(theme.id, tid)
            self.assertIn(THEMES[tid].palette()["bg"], app.styleSheet())
        self.assertEqual(seen[-5:], list(THEME_IDS))
        self.assertEqual([tuple(r) for r in self.ctx.db.query("SELECT * FROM tasks")], [tuple(r) for r in before])
        self.assertEqual(len(self.ctx.notes.list()), 1)

    def test_theme_accent_and_scale_persist_across_restart(self):
        self.ctx.settings.set("theme", "zen")
        set_accent(self.ctx.settings, "zen", "moss")
        self.ctx.settings.set("font_scale", 1.1)
        self.assertEqual(theme.tokens["accent"], THEMES["zen"].palette("moss")["accent"])
        self.assertAlmostEqual(app.font().pointSizeF(), 10.5 * 1.1, places=2)
        self.reopen()
        theme.apply("paper", accent=None, scale=1.0)
        apply_from_settings(self.ctx.settings)
        self.assertEqual((theme.id, theme.accent, theme.scale), ("zen", "moss", 1.1))

    def test_invalid_appearance_values_are_rejected(self):
        with self.assertRaises(ValueError):
            self.ctx.settings.set("theme", "neon")
        with self.assertRaises(ValueError):
            self.ctx.settings.set("font_scale", 3.0)
        self.assertIn(1.25, FONT_SCALES)

    def test_system_preference_maps_to_paper_or_midnight(self):
        self.ctx.settings.set("theme", "system")
        self.assertIn(theme.id, ("paper", "midnight"))


class MigrationV2Tests(TempHomeTestCase):
    def _make_v1_database(self, theme_value: str, with_task: bool) -> None:
        from src.database.schema import SCHEMA_V1, _split_sql

        self.ctx.close()
        self.paths.db_path.unlink()
        for suffix in ("-wal", "-shm"):
            p = self.paths.db_path.with_name(self.paths.db_path.name + suffix)
            if p.exists():
                p.unlink()
        conn = sqlite3.connect(self.paths.db_path)
        for statement in _split_sql(SCHEMA_V1):
            conn.execute(statement)
        conn.execute("INSERT INTO settings (key, value) VALUES ('theme', ?)", (json.dumps(theme_value),))
        if with_task:
            conn.execute("INSERT INTO tasks (title, created_at) VALUES ('v1 task', '2026-09-01 10:00:00')")
        conn.execute("PRAGMA user_version = 1")
        conn.commit()
        conn.close()

    def test_v1_user_keeps_data_theme_and_sidebar(self):
        self._make_v1_database("dark", with_task=True)
        self.reopen()
        self.assertEqual(self.ctx.settings.get("theme"), "midnight")
        self.assertEqual(self.ctx.settings.get("nav.modules"),
                         ["today", "tasks", "calendar", "study", "exams", "notes", "habits", "goals", "insights"])
        self.assertTrue(self.ctx.settings.get("onboarded"))
        self.assertEqual([t.title for t in self.ctx.tasks.list("all")], ["v1 task"])
        backups = list(self.paths.backups_dir.glob("*pre-upgrade*.db")) or list(self.paths.backups_dir.glob("*.db"))
        self.assertTrue(backups, "a backup is taken before upgrading a v1 database")

    def test_empty_v1_database_gets_profile_defaults(self):
        self._make_v1_database("light", with_task=False)
        self.reopen()
        self.assertEqual(self.ctx.settings.get("theme"), "paper")
        self.assertIsNone(self.ctx.settings.get("nav.modules"))


class NavigationTests(TempHomeTestCase):
    def setUp(self):
        super().setUp()
        from src.ui.main_window import MainWindow

        theme.set_asset_dir(self.paths.cache_dir)
        theme.apply("paper")
        self.window = MainWindow(self.ctx)
        self.window.show()
        app.processEvents()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        app.processEvents()
        super().tearDown()

    def test_registry_factories_import(self):
        for spec in registry.MODULES + [registry.SETTINGS]:
            cls = registry.load_class(spec)
            self.assertTrue(callable(cls), spec.key)

    def test_pages_are_created_lazily(self):
        created = set(self.window.pages)
        self.assertTrue({"today", "study"} <= created)
        self.assertNotIn("insights", created)
        self.window.navigate("insights")
        self.assertIn("insights", self.window.pages)

    def test_profile_and_module_choice_drive_the_sidebar(self):
        self.assertNotIn("exams", self.window.nav_buttons)  # "general" profile
        self.ctx.settings.set("profile", "school")
        self.assertIn("exams", self.window.nav_buttons)
        self.ctx.settings.set("nav.modules", ["today", "tasks", "notes"])
        self.assertEqual(set(self.window.nav_buttons) - {"settings"}, {"today", "tasks", "notes"})
        self.window.navigate("habits")  # hidden modules stay reachable
        self.assertIs(self.window.current_page(), self.window.pages["habits"])

    def test_ctrl_number_follows_visible_order(self):
        self.window._goto_index(1)
        self.assertEqual(self.window.current_key(), self.window.visible_keys[1])


if __name__ == "__main__":
    unittest.main()
