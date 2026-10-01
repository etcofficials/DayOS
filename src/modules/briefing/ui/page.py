"""Briefing page: today's weather and a quiet list of headlines from the topics you chose."""

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QVBoxLayout, QWidget

from src.modules.briefing import news
from src.modules.briefing.ui import cards
from src.ui.pages.base import Page
from src.ui.widgets.common import Card, PageHeader, SegmentBar, button, label, scroll_wrap


class BriefingPage(Page):
    domains = ("briefing", "settings")
    title = "Briefing"

    def __init__(self, ctx, window) -> None:
        super().__init__(ctx, window)
        self.controller = window.briefing
        header = PageHeader("Briefing", "Weather and headlines you chose, refreshed only when needed. Everything else "
                                        "in DayOS works offline.", eyebrow="Outside world")
        header.add_action(button("Mark all read", "ghost", "check", self.mark_all_read))
        header.add_action(button("Settings", "ghost", "settings", self.open_settings))
        header.add_action(button("Refresh", "soft", "refresh", self.refresh_all))
        self.root.addWidget(header)
        holder = QWidget()
        body = QVBoxLayout(holder)
        body.setContentsMargins(0, 0, 6, 0)
        body.setSpacing(14)
        self.weather_card = Card("Weather", "sun")
        self.weather_box = QVBoxLayout()
        self.weather_card.body.addLayout(self.weather_box)
        body.addWidget(self.weather_card)
        self.news_card = Card("Headlines", "news")
        filters = QHBoxLayout()
        self.topic_bar_holder = QHBoxLayout()
        filters.addLayout(self.topic_bar_holder, 1)
        self.unread = QCheckBox("Unread only")
        self.unread.toggled.connect(lambda _v: self._fill_news())
        filters.addWidget(self.unread)
        self.news_card.body.addLayout(filters)
        self.news_box = QVBoxLayout()
        self.news_card.body.addLayout(self.news_box)
        self.news_card.body.addWidget(label("Headlines and descriptions come from each publisher's own feed; open the "
                                            "article to read it on their site.", "caption", wrap=True))
        body.addWidget(self.news_card)
        body.addStretch(1)
        self.root.addWidget(scroll_wrap(holder), 1)
        self.topic_bar: SegmentBar | None = None
        self._topic = ""
        self.controller.weather_changed.connect(self._fill_weather)
        self.controller.news_changed.connect(self._fill_news)

    def open_settings(self) -> None:
        self.main.navigate("settings")
        self.main.page("settings").show_section("briefing")

    def refresh(self) -> None:
        topics = list(self.ctx.settings.get("news.topics"))
        options = [("", "All")] + [(t, news.TOPICS.get(t, t)) for t in topics]
        if self.topic_bar is not None:
            self.topic_bar.setParent(None)
            self.topic_bar.deleteLater()
        if self._topic not in topics:
            self._topic = ""
        self.topic_bar = SegmentBar(options, self._topic)
        self.topic_bar.changed.connect(self._set_topic)
        self.topic_bar.setVisible(len(topics) > 1)
        self.topic_bar_holder.addWidget(self.topic_bar)
        self._fill_weather()
        self._fill_news()
        self.controller.refresh_weather()
        self.controller.refresh_news()

    def _set_topic(self, topic: str) -> None:
        self._topic = topic
        self._fill_news()

    def _fill_weather(self) -> None:
        cards.fill_weather(self.weather_box, self.controller, compact=False, open_settings=self.open_settings)

    def _fill_news(self) -> None:
        cards.fill_news(self.news_box, self.controller, 60, self.open_settings, topic=self._topic or None,
                        unread_only=self.unread.isChecked())

    def refresh_all(self) -> None:
        self.controller.refresh_weather(force=True)
        self.controller.refresh_news(force=True)

    def mark_all_read(self) -> None:
        articles, _when = self.controller.articles()
        self.controller.mark_read([a.id for a in articles])
