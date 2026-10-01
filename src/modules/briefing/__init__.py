"""Briefing: optional weather (Open-Meteo) and a quiet news briefing (publishers' RSS feeds).

Both are off until the user turns them on; nothing is fetched on start-up unless a
cached copy is older than the chosen interval and the feature is enabled.
"""

from __future__ import annotations

from src.modules import registry
from src.modules.registry import ModuleSpec

registry.register(ModuleSpec(
    "briefing", "Briefing", "news", "life", "src.modules.briefing.ui.page:BriefingPage",
    "Weather and a quiet headline briefing from topics you choose (both optional)."))


def install(window) -> None:
    from PySide6.QtWidgets import QVBoxLayout

    from src.modules.briefing.ui import cards
    from src.modules.briefing.ui.controller import BriefingController
    from src.ui import settings_sections
    from src.ui.shell.commands import Command
    from src.ui.widgets.common import Card

    controller = BriefingController(window.ctx)
    window.briefing = controller

    def open_settings() -> None:
        window.navigate("settings")
        window.page("settings").show_section("briefing")

    today = window.pages["today"]
    w_card = Card("Weather", "sun")
    w_box = QVBoxLayout()
    w_card.body.addLayout(w_box)

    def fill_weather(_card, _day) -> None:
        cards.fill_weather(w_box, controller, compact=True, open_settings=open_settings)
        controller.refresh_weather()  # only if stale, enabled and not recently failed

    n_card = Card("News briefing", "news")
    n_box = QVBoxLayout()
    n_card.body.addLayout(n_box)

    def fill_news(_card, _day) -> None:
        cards.fill_news(n_box, controller, 5, open_settings, show_summary=False, unread_only=True)
        controller.refresh_news()

    today.register_widget("weather", w_card, fill_weather)
    today.register_widget("news", n_card, fill_news)
    controller.weather_changed.connect(lambda: fill_weather(w_card, None) if w_card.isVisible() else None)
    controller.news_changed.connect(lambda: fill_news(n_card, None) if n_card.isVisible() else None)

    from src.modules.briefing.ui.settings import build

    settings_sections.register(settings_sections.SectionSpec("briefing", "Weather & news", "sun", 50, build))
    window.commands.add(Command("briefing.open", "Weather and news", "Open the briefing", "", "news",
                                lambda: window.navigate("briefing"), ("weather", "forecast", "news", "headlines")))
    window.commands.add(Command("briefing.refresh", "Refresh weather and news", "Fetch the latest now", "",
                                "refresh", lambda: (controller.refresh_weather(force=True),
                                                    controller.refresh_news(force=True)), ("weather", "news")))
