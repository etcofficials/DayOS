"""Dashboard layout: cards flow into balanced columns that adapt to the window width.

Each card goes into the currently shortest column (in order), so the layout
stays tidy whichever widgets the user shows. Cards are only re-distributed when
the column count or the set of cards changes, so ticking a task never makes the
dashboard jump around.
"""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget


class DashboardColumns(QWidget):
    def __init__(self, breakpoints: tuple[int, int] = (820, 1250), spacing: int = 16,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._breakpoints = breakpoints
        self._spacing = spacing
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(spacing)
        self._columns: list[QVBoxLayout] = []
        self._widgets: list[QWidget] = []
        self._count = 0
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def column_count(self, width: int | None = None) -> int:
        w = self.width() if width is None else width
        if w < self._breakpoints[0]:
            return 1
        if w < self._breakpoints[1]:
            return 2
        return 3

    def widgets(self) -> list[QWidget]:
        return list(self._widgets)

    def set_widgets(self, widgets: list[QWidget]) -> None:
        if widgets == self._widgets:
            return
        for old in self._widgets:
            if old not in widgets:
                old.hide()
        self._widgets = list(widgets)
        self.relayout(force=True)

    # Qt's nested box layouts under-report height-for-width here (cards end up squeezed), so the
    # widget answers the question itself: the tallest column at the given width.
    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        count = self.column_count(width)
        if count != self._count or not self._columns:
            count = max(1, self._count)
        col_width = max(120, (width - (count - 1) * self._spacing) // count)
        best = 0
        for col in self._columns:
            total, n = 0, 0
            for i in range(col.count()):
                widget = col.itemAt(i).widget()
                if widget is None or widget.isHidden():
                    continue
                h = widget.heightForWidth(col_width) if widget.hasHeightForWidth() else widget.sizeHint().height()
                total += max(h, widget.minimumSizeHint().height())
                n += 1
            best = max(best, total + max(0, n - 1) * self._spacing)
        return best

    def minimumSizeHint(self):  # noqa: N802
        hint = super().minimumSizeHint()
        hint.setHeight(self.heightForWidth(max(self.width(), 400)))
        return hint

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self.column_count() != self._count:
            self.relayout(force=True)

    def relayout(self, force: bool = False) -> None:
        count = self.column_count()
        if count == self._count and not force:
            return
        self._count = count
        for col in self._columns:
            while col.count():
                col.takeAt(0)
            self._row.removeItem(col)
            col.deleteLater()
        self._columns = []
        for _ in range(count):
            col = QVBoxLayout()
            col.setContentsMargins(0, 0, 0, 0)
            col.setSpacing(self._spacing)
            col.addStretch(1)
            self._row.addLayout(col, 1)
            self._columns.append(col)
        width = max(1, self.width() or 1000)
        col_width = max(200, (width - (count - 1) * self._spacing) // count)
        heights = [0] * count
        for widget in self._widgets:
            if widget.hasHeightForWidth():
                h = widget.heightForWidth(col_width)
            else:
                h = widget.sizeHint().height()
            index = min(range(count), key=lambda i: (heights[i], i))
            col = self._columns[index]
            col.insertWidget(col.count() - 1, widget)
            widget.show()
            heights[index] += max(h, 60) + self._spacing
