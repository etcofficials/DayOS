"""Weather and news cards, shared by the Today dashboard and the Briefing page."""

from __future__ import annotations

from datetime import date, datetime, timezone

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMenu, QToolButton, QVBoxLayout, QWidget

from src.modules.briefing import news, weather
from src.services.http import describe_age
from src.ui.icons import icon
from src.ui.widgets.common import button, clear_layout, label, tool_button


def _fmt(value, unit: str = "", digits: int = 0) -> str | None:
    if value is None:
        return None
    return f"{value:.{digits}f}{unit}"


def fill_weather(box: QVBoxLayout, controller, compact: bool, open_settings) -> None:
    clear_layout(box)
    s = controller.ctx.settings
    place = weather.Place.from_setting(s.get("weather.place"))
    if not s.get("weather.enabled") or place is None:
        box.addWidget(label("Weather is off. Choose a place in Settings → Weather & news to see current "
                            "conditions here.", "muted", wrap=True))
        row = QHBoxLayout()
        row.addWidget(button("Set up weather", "link", "sun", open_settings))
        row.addStretch(1)
        box.addLayout(row)
        return
    report, when = controller.weather()
    if report is None:
        text = ("Getting the weather…" if controller.weather_busy else
                f"No weather yet. {controller.weather_error or 'Press refresh to fetch it.'}")
        box.addWidget(label(text, "muted", wrap=True))
    else:
        text, ic = weather.describe(report.code)
        top = QHBoxLayout()
        pic = QLabel()
        pic.setPixmap(icon(ic if report.is_day or ic != "sun" else "moon", "accent", 34).pixmap(34, 34))
        top.addWidget(pic)
        col = QVBoxLayout()
        col.setSpacing(0)
        temp = _fmt(report.temperature, report.temp_unit)
        col.addWidget(label(temp or "—", "metric"))
        col.addWidget(label(f"{text} · {report.place}", "caption", wrap=True))
        top.addLayout(col, 1)
        box.addLayout(top)
        bits = []
        if report.feels_like is not None:
            bits.append(f"Feels like {_fmt(report.feels_like, report.temp_unit)}")
        if report.humidity is not None:
            bits.append(f"Humidity {report.humidity}%")
        if report.rain_chance is not None:
            bits.append(f"Rain chance {report.rain_chance}%")
        if report.wind_speed is not None:
            bits.append(f"Wind {_fmt(report.wind_speed)} {report.wind_unit} {weather.compass(report.wind_direction)}".strip())
        if bits:
            box.addWidget(label(" · ".join(bits), "", wrap=True))
        if report.days and not compact:
            row = QHBoxLayout()
            for d in report.days[:4]:
                cell = QVBoxLayout()
                cell.setSpacing(1)
                try:
                    name = "Today" if d.date == date.today().isoformat() else date.fromisoformat(d.date).strftime("%a")
                except ValueError:
                    name = d.date
                cell.addWidget(label(name, "caption"))
                cell.addWidget(label(weather.describe(d.code)[0], "", wrap=True))
                hi, lo = _fmt(d.high, "°"), _fmt(d.low, "°")
                cell.addWidget(label(" / ".join(x for x in (hi, lo) if x) or "—", "caption"))
                if d.rain_chance is not None:
                    cell.addWidget(label(f"Rain {d.rain_chance}%", "caption"))
                row.addLayout(cell, 1)
            box.addLayout(row)
        elif report.days and compact and report.days[0].high is not None:
            d = report.days[0]
            box.addWidget(label(f"Today {_fmt(d.high, '°')} / {_fmt(d.low, '°')}", "caption"))
    status = QHBoxLayout()
    parts = []
    if when is not None:
        parts.append(f"Updated {describe_age(when)}")
    if controller.weather_error and report is not None:
        parts.append("offline — showing the last saved weather")
    if controller.weather_busy:
        parts.append("refreshing…")
    status.addWidget(label(" · ".join(parts), "caption", wrap=True), 1)
    status.addWidget(tool_button("refresh", "Refresh weather", lambda: controller.refresh_weather(force=True), 14))
    box.addLayout(status)
    attribution = QLabel(f'<a href="{weather.ATTRIBUTION_URL}">{weather.ATTRIBUTION}</a>')
    attribution.setProperty("role", "caption")
    attribution.setOpenExternalLinks(True)
    box.addWidget(attribution)


def published_text(article: news.Article) -> str:
    dt = article.published_dt
    if dt is None:
        return "date not given"
    local = dt.astimezone()
    return describe_age(local.replace(tzinfo=None), datetime.now())


def fill_news(box: QVBoxLayout, controller, limit: int, open_settings, show_summary: bool = True,
              topic: str | None = None, unread_only: bool = False) -> int:
    """Returns how many articles were shown."""
    clear_layout(box)
    s = controller.ctx.settings
    if not s.get("news.enabled") or not s.get("news.topics"):
        box.addWidget(label("The news briefing is off. Pick topics in Settings → Weather & news.", "muted",
                            wrap=True))
        row = QHBoxLayout()
        row.addWidget(button("Choose topics", "link", "news", open_settings))
        row.addStretch(1)
        box.addLayout(row)
        return 0
    articles, when = controller.articles()
    read = controller.read_ids()
    if topic:
        articles = [a for a in articles if a.topic == topic]
    if unread_only:
        articles = [a for a in articles if a.id not in read]
    shown = 0
    for a in articles[:limit]:
        box.addWidget(_article_row(a, a.id in read, controller, show_summary))
        shown += 1
    if not shown:
        msg = ("Fetching headlines…" if controller.news_busy else
               "No headlines to show." + (" Some sources couldn't be reached." if controller.news_errors else
                                          " Press refresh to fetch them."))
        box.addWidget(label(msg, "muted", wrap=True))
    status = QHBoxLayout()
    parts = []
    if when is not None:
        stale = (datetime.now() - when).total_seconds() > int(s.get("news.refresh_minutes")) * 60
        parts.append(("Saved headlines from " if stale else "Updated ") + describe_age(when))
    if controller.news_errors:
        parts.append(f"{len(controller.news_errors)} source(s) unavailable")
    if controller.news_busy:
        parts.append("refreshing…")
    status.addWidget(label(" · ".join(parts), "caption", wrap=True), 1)
    status.addWidget(tool_button("refresh", "Refresh news", lambda: controller.refresh_news(force=True), 14))
    box.addLayout(status)
    return shown


def _article_row(a: news.Article, read: bool, controller, show_summary: bool) -> QWidget:
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 2, 0, 6)
    lay.setSpacing(2)
    top = QHBoxLayout()
    title = button(a.title, "link", on_click=lambda: _open(a, controller))
    title.setToolTip(a.link)
    title.setStyleSheet("text-align: left;" + ("" if read else " font-weight: 600;"))
    top.addWidget(title, 1)
    more = tool_button("more", "More", None, 14)
    more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    menu = QMenu(more)
    menu.addAction("Mark as read", lambda: controller.mark_read([a.id]))
    menu.addAction(f"Hide {a.publisher}", lambda: controller.hide_source(a.publisher))
    more.setMenu(menu)
    top.addWidget(more)
    lay.addLayout(top)
    meta = f"{a.publisher} · {published_text(a)} · {news.TOPICS.get(a.topic, a.topic)}" + ("" if read else " · new")
    lay.addWidget(label(meta, "caption", wrap=True))
    if show_summary and a.summary:
        lay.addWidget(label(f"Publisher's description: {a.summary}", "muted", wrap=True))
    return w


def _open(a: news.Article, controller) -> None:
    if a.link.startswith(("https://", "http://")):
        QDesktopServices.openUrl(QUrl(a.link))
    controller.mark_read([a.id])
