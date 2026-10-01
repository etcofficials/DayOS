"""Preview every proposed file operation before anything happens."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from src.modules.filepilot.operations import PlannedOp
from src.modules.filepilot.scanner import human_size
from src.ui.widgets.common import FadeDialog, button, label

STATUS_TEXT = {"ready": "Ready", "conflict": "Name already exists", "blocked": "Won't be changed"}


class PreviewDialog(FadeDialog):
    """Shows exact paths, sizes, reasons, destinations and conflicts. ``conflict_mode`` is
    "skip" or "rename" after the dialog is accepted."""

    def __init__(self, ops: list[PlannedOp], parent=None, destination: str = "") -> None:
        super().__init__(parent)
        self.ops = ops
        self.conflict_mode = "skip"
        action = ops[0].action if ops else "move"
        runnable = [op for op in ops if op.status != "blocked"]
        conflicts = [op for op in ops if op.status == "conflict"]
        blocked = [op for op in ops if op.status == "blocked"]
        total = sum(op.size for op in runnable)
        self.setWindowTitle("Review before anything changes")
        self.setModal(True)
        self.resize(1000, 560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.setSpacing(10)
        lay.addWidget(label("Review before anything changes", "section"))
        n = len(runnable)
        files = f"{n} file{'s' if n != 1 else ''} ({human_size(total)})"
        if action == "move":
            summary = f"Move {files} to {destination}. Each move is checked afterwards and can be undone from History."
        else:
            summary = (f"Send {files} to the Recycle Bin. Nothing is deleted permanently: you can restore them from "
                       "the Recycle Bin until you empty it yourself.")
        lay.addWidget(label(summary, "", wrap=True))
        if blocked:
            lay.addWidget(label(f"{len(blocked)} file{'s' if len(blocked) != 1 else ''} will be left alone "
                                "(see the reasons below).", "warning", wrap=True))
        self.conflict_combo = QComboBox()
        self.conflict_combo.setAccessibleName("When a file with the same name exists")
        self.conflict_combo.addItem("Skip those files", "skip")
        self.conflict_combo.addItem("Keep both (the moved file gets a new name)", "rename")
        if conflicts:
            row = QHBoxLayout()
            row.addWidget(label(f"{len(conflicts)} name conflict{'s' if len(conflicts) != 1 else ''}. "
                                "Existing files are never replaced:", "warning"))
            row.addWidget(self.conflict_combo)
            row.addStretch(1)
            lay.addLayout(row)
        table = QTableWidget(len(ops), 6)
        table.setHorizontalHeaderLabels(["Status", "File", "Size", "Reason", "Destination", "Note"])
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.verticalHeader().setVisible(False)
        table.setAccessibleName("Proposed operations")
        for row_i, op in enumerate(ops):
            values = [STATUS_TEXT.get(op.status, op.status), op.source, human_size(op.size), op.reason,
                      op.destination if op.action == "move" else "Recycle Bin", op.note]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                table.setItem(row_i, col, item)
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        table.setColumnWidth(0, 130)
        table.setColumnWidth(1, 330)
        table.setColumnWidth(2, 80)
        table.setColumnWidth(3, 180)
        table.setColumnWidth(4, 200)
        self.table = table
        lay.addWidget(table, 1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(button("Cancel", "ghost", on_click=self.reject))
        verb = "Move" if action == "move" else "Send to Recycle Bin:"
        self.confirm_btn = button(f"{verb} {n} file{'s' if n != 1 else ''}", "primary" if action == "move" else "danger",
                                  on_click=self._confirm)
        self.confirm_btn.setEnabled(n > 0)
        buttons.addWidget(self.confirm_btn)
        lay.addLayout(buttons)

    def _confirm(self) -> None:
        self.conflict_mode = self.conflict_combo.currentData()
        self.accept()
