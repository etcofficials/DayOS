"""Widgets shared by the StudyForge tabs."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QTreeWidget, QTreeWidgetItem

from src.modules.studyforge.models import NODE_LABELS, Node

MASTERY_TONES = {"new": "", "learning": "terracotta", "developing": "amber", "strong": "accent"}


def sf(ctx):
    return ctx.services["studyforge"]


def svc(ctx):
    return ctx.services["studyforge.service"]


class NodeCombo(QComboBox):
    """Pick a node of a course, shown indented by level."""

    def __init__(self, none_label: str | None = "No topic", parent=None) -> None:
        super().__init__(parent)
        self._none = none_label
        self.setMinimumWidth(220)

    def load(self, roots: list[Node], current: int | None = None, kinds: set[str] | None = None) -> None:
        self.blockSignals(True)
        self.clear()
        if self._none is not None:
            self.addItem(self._none, None)

        def walk(nodes: list[Node], depth: int) -> None:
            for n in nodes:
                if kinds is None or n.kind in kinds:
                    self.addItem("    " * depth + n.title, n.id)
                walk(n.children, depth + 1)

        walk(roots, 0)
        index = self.findData(current) if current is not None else 0
        self.setCurrentIndex(max(0, index))
        self.blockSignals(False)

    def current_id(self) -> int | None:
        data = self.currentData()
        return int(data) if data is not None else None

    def set_current_id(self, node_id: int | None) -> None:
        index = self.findData(node_id) if node_id is not None else 0
        if index >= 0:
            self.setCurrentIndex(index)


class ScopeTree(QTreeWidget):
    """Checkable course map used to choose what a test or session covers."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setMinimumHeight(220)
        self.setAccessibleName("Topics to include")
        self.itemChanged.connect(self._changed)
        self._updating = False

    def load(self, roots: list[Node], checked: set[int] | None = None, counts: dict[int, int] | None = None) -> None:
        self._updating = True
        self.clear()
        counts = counts or {}

        def add(parent, nodes: list[Node]) -> None:
            for n in nodes:
                total = counts.get(n.id, 0)
                text = n.title + (f"   ({total} q)" if total else "")
                item = QTreeWidgetItem([text])
                item.setData(0, Qt.ItemDataRole.UserRole, n.id)
                item.setToolTip(0, NODE_LABELS.get(n.kind, n.kind))
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(0, Qt.CheckState.Checked if checked and n.id in checked else Qt.CheckState.Unchecked)
                (parent.addChild if isinstance(parent, QTreeWidgetItem) else parent.addTopLevelItem)(item)
                add(item, n.children)

        add(self, roots)
        self.expandToDepth(1)
        self._updating = False

    def _changed(self, item: QTreeWidgetItem, _col: int) -> None:
        if self._updating:
            return
        self._updating = True
        state = item.checkState(0)

        def down(it: QTreeWidgetItem) -> None:
            for i in range(it.childCount()):
                it.child(i).setCheckState(0, state)
                down(it.child(i))

        down(item)
        self._updating = False

    def checked_ids(self) -> list[int]:
        """Top-most checked nodes (descendants are implied)."""
        out: list[int] = []

        def walk(it: QTreeWidgetItem) -> None:
            if it.checkState(0) == Qt.CheckState.Checked:
                out.append(int(it.data(0, Qt.ItemDataRole.UserRole)))
                return
            for i in range(it.childCount()):
                walk(it.child(i))

        for i in range(self.topLevelItemCount()):
            walk(self.topLevelItem(i))
        return out

    def check_all(self, on: bool = True) -> None:
        for i in range(self.topLevelItemCount()):
            self.topLevelItem(i).setCheckState(0, Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)


def percent(value: float | None) -> str:
    return "–" if value is None else f"{round(value * 100)}%"
