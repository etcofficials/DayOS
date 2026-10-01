"""Settings → Weather & news. Both are off until switched on; both can be removed entirely."""

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QLineEdit, QSpinBox, QVBoxLayout, QWidget

from src.modules.briefing import news, weather
from src.repositories.notes import normalize_url
from src.services.dates import ValidationError
from src.ui.widgets.common import Card, button, clear_layout, label, show_error, tool_button
from src.ui.worker import run_in_background


def build(page) -> QWidget:
    ctx = page.ctx
    controller = page.main.briefing
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(16)

    # -- weather
    card = Card("Weather", "sun")
    w_on = QCheckBox("Show weather (asks Open-Meteo.com for the forecast; no account or key needed)")
    w_on.toggled.connect(lambda v: page.set_pref("weather.enabled", v))
    card.body.addWidget(w_on)
    current = label("", "", wrap=True)
    card.body.addWidget(current)
    row = QHBoxLayout()
    query = QLineEdit()
    query.setPlaceholderText("Search for your town or city")
    query.setAccessibleName("Place search")
    row.addWidget(query, 1)
    results = QComboBox()
    results.setAccessibleName("Matching places")
    results.hide()
    find_btn = button("Search", "soft", "search")
    row.addWidget(find_btn)
    card.body.addLayout(row)
    card.body.addWidget(results)
    use_btn = button("Use this place", "primary", "check")
    use_btn.hide()
    card.body.addWidget(use_btn)
    search_status = label("", "caption", wrap=True)
    card.body.addWidget(search_status)
    grid = QGridLayout()
    grid.addWidget(label("Units", "muted"), 0, 0)
    units = QComboBox()
    units.addItem("°C, km/h", "metric")
    units.addItem("°F, mph", "imperial")
    units.activated.connect(lambda _i: page.set_pref("weather.units", units.currentData()))
    grid.addWidget(units, 0, 1)
    grid.addWidget(label("Refresh at most every", "muted"), 1, 0)
    w_every = QSpinBox()
    w_every.setRange(30, 720)
    w_every.setSingleStep(30)
    w_every.setSuffix(" minutes")
    w_every.valueChanged.connect(lambda v: page.set_pref("weather.refresh_minutes", int(v)))
    grid.addWidget(w_every, 1, 1)
    card.body.addLayout(grid)
    card.body.addWidget(label("Only the place's coordinates are sent. Weather data by Open-Meteo.com (CC BY 4.0), "
                              "free for personal, non-commercial use.", "caption", wrap=True))
    lay.addWidget(card)

    found: list[weather.Place] = []

    def search() -> None:
        text = query.text().strip()
        if len(text) < 2:
            search_status.setText("Type at least two letters.")
            return
        search_status.setText("Searching…")
        find_btn.setEnabled(False)

        def done(places: list[weather.Place]) -> None:
            find_btn.setEnabled(True)
            found.clear()
            found.extend(places)
            results.clear()
            for p in places:
                results.addItem(p.label)
            results.setVisible(bool(places))
            use_btn.setVisible(bool(places))
            search_status.setText("" if places else "No places found. Try a nearby larger town.")

        def failed(exc: Exception) -> None:
            find_btn.setEnabled(True)
            search_status.setText(f"Couldn't search: {exc}")

        run_in_background(lambda: weather.search_places(text), done, failed)

    find_btn.clicked.connect(lambda _=False: search())
    query.returnPressed.connect(search)

    def use_place() -> None:
        if 0 <= results.currentIndex() < len(found):
            page.set_pref("weather.place", found[results.currentIndex()].to_setting())
            if not ctx.settings.get("weather.enabled"):
                page.set_pref("weather.enabled", True)
            results.hide()
            use_btn.hide()
            search_status.setText("")
            controller.refresh_weather(force=True)

    use_btn.clicked.connect(lambda _=False: use_place())

    # -- news
    card = Card("News briefing", "news")
    n_on = QCheckBox("Show a news briefing (reads publishers' public RSS feeds)")
    n_on.toggled.connect(lambda v: page.set_pref("news.enabled", v))
    card.body.addWidget(n_on)
    topics_grid = QGridLayout()
    topic_checks: dict[str, QCheckBox] = {}
    for i, (key, name) in enumerate(news.TOPICS.items()):
        cb = QCheckBox(name)
        topic_checks[key] = cb
        cb.toggled.connect(lambda _v: page.set_pref("news.topics", [k for k, c in topic_checks.items()
                                                                     if c.isChecked()]))
        topics_grid.addWidget(cb, i // 3, i % 3)
    card.body.addLayout(topics_grid)
    sources = label("", "caption", wrap=True)
    card.body.addWidget(sources)
    card.body.addWidget(label("Add your own feeds (for local news, a blog or a school site):", "muted", wrap=True))
    feeds_box = QVBoxLayout()
    card.body.addLayout(feeds_box)
    add_row = QHBoxLayout()
    f_name = QLineEdit()
    f_name.setPlaceholderText("Name, e.g. My city paper")
    f_url = QLineEdit()
    f_url.setPlaceholderText("Feed address (https://…/rss)")
    f_topic = QComboBox()
    for key, name in news.TOPICS.items():
        f_topic.addItem(name, key)
    f_topic.setCurrentIndex(f_topic.findData("local"))
    add_row.addWidget(f_name, 1)
    add_row.addWidget(f_url, 2)
    add_row.addWidget(f_topic)
    add_row.addWidget(button("Add feed", "soft", "plus", lambda: add_feed()))
    card.body.addLayout(add_row)
    hidden_box = QVBoxLayout()
    card.body.addLayout(hidden_box)
    grid = QHBoxLayout()
    grid.addWidget(label("Refresh at most every", "muted"))
    n_every = QSpinBox()
    n_every.setRange(60, 1440)
    n_every.setSingleStep(60)
    n_every.setSuffix(" minutes")
    n_every.valueChanged.connect(lambda v: page.set_pref("news.refresh_minutes", int(v)))
    grid.addWidget(n_every)
    grid.addStretch(1)
    card.body.addLayout(grid)
    card.body.addWidget(label("DayOS shows each publisher's headline and short description and links to the full "
                              "article on their site. It never sends news pop-ups.", "caption", wrap=True))
    lay.addWidget(card)

    def add_feed() -> None:
        try:
            url = normalize_url(f_url.text())
            name = f_name.text().strip()[:120]
            if not url or not name:
                raise ValidationError("Enter a name and a feed address.")
        except ValidationError as exc:
            show_error(page, "Check the feed", str(exc))
            return
        feeds = list(ctx.settings.get("news.custom_feeds"))
        feeds.append({"name": name, "url": url, "topic": f_topic.currentData()})
        page.set_pref("news.custom_feeds", feeds[-30:])
        topics = list(ctx.settings.get("news.topics"))
        if f_topic.currentData() not in topics:
            topic_checks[f_topic.currentData()].setChecked(True)
        f_name.clear()
        f_url.clear()
        load()

    def remove_feed(index: int) -> None:
        feeds = list(ctx.settings.get("news.custom_feeds"))
        if 0 <= index < len(feeds):
            feeds.pop(index)
            page.set_pref("news.custom_feeds", feeds)
            load()

    def unhide(name: str) -> None:
        page.set_pref("news.hidden_sources", [h for h in ctx.settings.get("news.hidden_sources") if h != name])
        load()

    def load() -> None:
        s = ctx.settings
        place = weather.Place.from_setting(s.get("weather.place"))
        w_on.setChecked(bool(s.get("weather.enabled")))
        current.setText(f"Place: {place.label}" if place else "No place chosen yet.")
        units.setCurrentIndex(max(0, units.findData(s.get("weather.units"))))
        w_every.setValue(int(s.get("weather.refresh_minutes")))
        n_on.setChecked(bool(s.get("news.enabled")))
        chosen = set(s.get("news.topics"))
        for key, cb in topic_checks.items():
            cb.blockSignals(True)
            cb.setChecked(key in chosen)
            cb.blockSignals(False)
        names = [f.name for f in controller.feeds()]
        sources.setText("Sources: " + ", ".join(names) if names else "Choose topics to see their sources.")
        n_every.setValue(int(s.get("news.refresh_minutes")))
        clear_layout(feeds_box)
        for i, f in enumerate(s.get("news.custom_feeds")):
            r = QHBoxLayout()
            r.addWidget(label(f"{f['name']} · {news.TOPICS.get(f['topic'], f['topic'])} · {f['url']}", "", wrap=True), 1)
            r.addWidget(tool_button("close", "Remove feed", lambda idx=i: remove_feed(idx), 14))
            feeds_box.addLayout(r)
        clear_layout(hidden_box)
        for name in s.get("news.hidden_sources"):
            r = QHBoxLayout()
            r.addWidget(label(f"Hidden source: {name}", "caption"), 1)
            r.addWidget(button("Show again", "link", on_click=lambda n=name: unhide(n)))
            hidden_box.addLayout(r)

    page.on_refresh(load)
    return box
