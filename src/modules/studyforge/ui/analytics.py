"""StudyForge analytics: only real results; estimates and non-comparable tests are kept apart."""

from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QVBoxLayout, QWidget

from src.modules.studyforge.models import QTYPES
from src.modules.studyforge.ui.common import svc
from src.ui.widgets.charts import HBarList, LineChart
from src.ui.widgets.common import Card, EmptyState, clear_layout, label, scroll_wrap


class AnalyticsTab(QWidget):
    def __init__(self, page) -> None:
        super().__init__()
        self.page = page
        self.ctx = page.ctx
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 12, 0, 0)
        self.holder = QWidget()
        self.body = QVBoxLayout(self.holder)
        self.body.setContentsMargins(0, 0, 6, 0)
        self.body.setSpacing(14)
        lay.addWidget(scroll_wrap(self.holder), 1)

    def refresh(self) -> None:
        clear_layout(self.body)
        data = svc(self.ctx).analytics(self.page.course_id)
        history = data["history"]
        if not history:
            self.body.addWidget(EmptyState("chart", "No results yet",
                                           "Take a practice test and your results will appear here — nothing is "
                                           "estimated or filled in.", compact=True))
            self.body.addStretch(1)
            return
        top = QHBoxLayout()
        marked = [h for h in history if h["status"] == "marked"]
        for value, caption in ((str(len(history)), "tests taken"),
                               (f"{sum(h['percent'] for h in marked) / len(marked):.0f}%" if marked else "–",
                                "average (fully marked tests)"),
                               (str(data["revisions_done"]), "revision activities, last 30 days")):
            col = QVBoxLayout()
            col.addWidget(label(value, "metric"))
            col.addWidget(label(caption, "metricLabel"))
            top.addLayout(col)
        top.addStretch(1)
        self.body.addLayout(top)
        grid = QGridLayout()
        grid.setSpacing(14)
        hist = Card("Test history", "chart")
        lines = [f"{h['date']} · {h['title']}: {h['percent']:.0f}%"
                 + ("" if h["status"] == "marked" else " (written answers not all marked yet)")
                 + (" · includes AI estimates" if h["estimates"] else "") for h in history[:10]]
        for line in lines:
            hist.body.addWidget(label(line, "", wrap=True))
        grid.addWidget(hist, 0, 0)
        comp = Card("Progress on comparable tests", "insights")
        if data["comparable"]:
            comp.body.addWidget(label("Only tests with the same topics, structure and difficulty are compared.",
                                      "caption", wrap=True))
            for _sig, series in list(data["comparable"].items())[:3]:
                chart = LineChart("accent")
                chart.setMinimumHeight(140)
                chart.set_points([(p["date"][5:], p["percent"], f"{p['title']}: {p['percent']}%") for p in series])
                comp.body.addWidget(label(series[-1]["title"], "heading"))
                comp.body.addWidget(chart)
        else:
            comp.body.addWidget(label("Repeat a test with the same settings to see a fair comparison over time. "
                                      "Scores from different kinds of tests aren't compared.", "muted", wrap=True))
        grid.addWidget(comp, 0, 1)
        topics = Card("Topic accuracy (weakest first)", "book")
        if data["by_topic"]:
            bars = HBarList()
            bars.set_rows([(name, pct / 100, f"{pct:.0f}% of {total:g} marks",
                            "danger" if pct < 50 else "amber" if pct < 75 else "accent")
                           for name, pct, total in data["by_topic"][:12]])
            topics.body.addWidget(bars)
        grid.addWidget(topics, 1, 0)
        types = Card("By question type", "grid")
        if data["by_type"]:
            bars = HBarList()
            bars.set_rows([(QTYPES.get(k, k), v / 100, f"{v:.0f}%", "blue") for k, v in
                           sorted(data["by_type"].items(), key=lambda x: x[1])])
            types.body.addWidget(bars)
        grid.addWidget(types, 1, 1)
        mistakes = Card("Mistake categories", "mistake")
        if data["mistakes"]:
            total = sum(n for _, n in data["mistakes"])
            bars = HBarList()
            bars.set_rows([(c, n / total, str(n), "terracotta") for c, n in data["mistakes"][:8]])
            mistakes.body.addWidget(bars)
        else:
            mistakes.body.addWidget(label("No mistakes recorded.", "muted"))
        grid.addWidget(mistakes, 2, 0)
        if data["estimated_answers"]:
            note = Card("About estimates", "sparkle")
            note.body.addWidget(label(f"{data['estimated_answers']} written answer(s) only have an AI estimate. They "
                                      "are left out of accuracy figures until you mark them yourself.", "muted", wrap=True))
            grid.addWidget(note, 2, 1)
        for c in range(2):
            grid.setColumnStretch(c, 1)
        self.body.addLayout(grid)
        self.body.addStretch(1)
