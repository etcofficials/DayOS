"""Skills page: roadmaps for what you're learning, and a weekly look at what you did and made."""

from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from src.modules.skills.repository import CATEGORY_SUGGESTIONS, ITEM_KINDS, MODES, STATUSES, SkillRepository
from src.services.dates import format_duration, today, week_start
from src.ui.bus import bus
from src.ui.pages.base import Page
from src.ui.widgets.common import (
    Card,
    EmptyState,
    FormDialog,
    OptionalDate,
    PageHeader,
    SegmentBar,
    button,
    chip,
    clear_layout,
    confirm,
    guarded,
    label,
    min_width_floor,
    scroll_wrap,
    tool_button,
)

MODE_SHORT = {"learn": "Learning", "practice": "Practice", "build": "Building"}


class SkillDialog(FormDialog):
    def __init__(self, page: "SkillsPage", skill=None) -> None:
        super().__init__("Edit skill" if skill else "New skill", page, "Save", 540)
        self.page = page
        self.skill = skill
        self.saved_id: int | None = None
        self.name = QLineEdit(skill.name if skill else "")
        self.name.setMaxLength(80)
        self.name.setPlaceholderText("e.g. Python, Video editing, Spanish")
        self.add_row("Skill", self.name)
        self.category = QComboBox()
        self.category.setEditable(True)
        self.category.addItems([""] + CATEGORY_SUGGESTIONS)
        self.category.setCurrentText(skill.category if skill else "")
        self.add_row("Area", self.category)
        self.baseline = QPlainTextEdit(skill.baseline if skill else "")
        self.baseline.setPlaceholderText("Where you are now, in your own words")
        self.baseline.setFixedHeight(64)
        self.add_row("Starting point", self.baseline)
        self.goal = QPlainTextEdit(skill.goal if skill else "")
        self.goal.setPlaceholderText("What you'd like to be able to do")
        self.goal.setFixedHeight(64)
        self.add_row("Desired outcome", self.goal)
        self.status = QComboBox()
        for key, text in STATUSES.items():
            self.status.addItem(text, key)
        self.status.setCurrentIndex(max(0, self.status.findData(skill.status if skill else "active")))
        self.add_row("Status", self.status)
        review = date.fromisoformat(skill.review_date) if skill and skill.review_date else None
        self.review = OptionalDate("Review on", review or today() + timedelta(days=30))
        self.review.check.setChecked(review is not None)
        self.add_row("Review", self.review)

    def save(self) -> None:
        self.saved_id = self.page.skills.save(
            self.skill.id if self.skill else None, name=self.name.text(), category=self.category.currentText(),
            baseline=self.baseline.toPlainText(), goal=self.goal.toPlainText(), status=self.status.currentData(),
            review_date=self.review.value(), notes=self.skill.notes if self.skill else "")


class SkillsPage(Page):
    domains = ("skills", "links", "settings")
    title = "Skills"

    def __init__(self, ctx, window) -> None:
        super().__init__(ctx, window)
        self.skills = SkillRepository(ctx.db)
        self.current_id: int | None = None
        header = PageHeader("Skills", "Roadmaps for what you're learning. Progress is what you practise and make — "
                                      "no scores.", eyebrow="Growth")
        header.add_action(button("New skill", "primary", "plus", self.new_item, "New skill (Ctrl+N)"))
        self.root.addWidget(header)
        self.view = SegmentBar([("skills", "Skills"), ("week", "This week")], "skills")
        self.view.changed.connect(lambda _k: self.refresh())
        self.root.addWidget(self.view, 0, Qt.AlignmentFlag.AlignLeft)

        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.split.setChildrenCollapsible(False)
        self.split.setHandleWidth(14)
        left = QFrame()
        left.setProperty("panel", True)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(12, 12, 12, 12)
        self.list = QListWidget()
        self.list.setAccessibleName("Skills")
        self.list.currentItemChanged.connect(self._on_select)
        ll.addWidget(self.list, 1)
        min_width_floor(left, 240)
        self.split.addWidget(left)
        self.detail_holder = QWidget()
        self.detail = QVBoxLayout(self.detail_holder)
        self.detail.setContentsMargins(0, 0, 6, 0)
        self.detail.setSpacing(14)
        self.split.addWidget(scroll_wrap(self.detail_holder))
        self.split.setSizes([280, 760])
        self.root.addWidget(self.split, 1)

        self.week_holder = QWidget()
        self.week = QVBoxLayout(self.week_holder)
        self.week.setContentsMargins(0, 0, 6, 0)
        self.week.setSpacing(14)
        self.week_scroll = scroll_wrap(self.week_holder)
        self.root.addWidget(self.week_scroll, 1)

    # -- list -----------------------------------------------------------------------------
    def refresh(self) -> None:
        weekly = self.view.current() == "week"
        self.split.setVisible(not weekly)
        self.week_scroll.setVisible(weekly)
        if weekly:
            self._fill_week()
            return
        skills = self.skills.list()
        self.list.blockSignals(True)
        self.list.clear()
        due = {s.id for s in self.skills.due_reviews()}
        for s in skills:
            extra = " · review due" if s.id in due else "" if s.status == "active" else f" · {STATUSES[s.status].lower()}"
            item = QListWidgetItem(f"{s.name}\n{s.category or 'Skill'}{extra}")
            item.setData(Qt.ItemDataRole.UserRole, s.id)
            self.list.addItem(item)
            if s.id == self.current_id:
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)
        if self.current_id is None and skills:
            self.current_id = skills[0].id
            self.list.setCurrentRow(0)
        self._fill_detail()

    def _on_select(self, item, _prev) -> None:
        if item is not None:
            self.current_id = int(item.data(Qt.ItemDataRole.UserRole))
            self._fill_detail()

    def new_item(self) -> None:
        dlg = SkillDialog(self)
        if dlg.exec():
            self.current_id = dlg.saved_id
            self.view.set_current("skills")
            bus.notify("skills")
            self.refresh()

    def open_skill(self, skill_id: int) -> None:
        self.current_id = skill_id
        self.view.set_current("skills")
        self.refresh()

    # -- detail -----------------------------------------------------------------------------
    def _fill_detail(self) -> None:
        clear_layout(self.detail)
        skill = self.skills.get(self.current_id) if self.current_id else None
        if skill is None:
            self.detail.addWidget(EmptyState("skill", "No skills yet",
                                             "Add something you want to get better at — a language, coding, drawing, "
                                             "public speaking — and plan small steps.", [("New skill", self.new_item)]))
            self.detail.addStretch(1)
            return
        top = Card(skill.name, "skill")
        row = QHBoxLayout()
        if skill.category:
            row.addWidget(chip(skill.category))
        row.addWidget(chip(STATUSES[skill.status], "accent" if skill.status == "active" else ""))
        if skill.review_date:
            row.addWidget(chip(f"Review {skill.review_date}", "amber" if skill.review_date <= today().isoformat() else ""))
        row.addStretch(1)
        row.addWidget(button("Edit", "link", "edit", lambda: self.edit(skill)))
        row.addWidget(button("Delete", "link", "trash", lambda: self.delete(skill)))
        top.body.addLayout(row)
        for title, text in (("Starting point", skill.baseline), ("Desired outcome", skill.goal)):
            if text:
                top.body.addWidget(label(title, "caption"))
                top.body.addWidget(label(text, "", wrap=True))
        self.detail.addWidget(top)

        prereq = Card("Builds on", "link")
        chips = QHBoxLayout()
        reqs = self.skills.prerequisites(skill.id)
        for r in reqs:
            chips.addWidget(button(r.name, "ghost", on_click=lambda rid=r.id: self.open_skill(rid)))
            chips.addWidget(tool_button("close", f"Remove {r.name}", lambda rid=r.id: self._remove_prereq(skill.id, rid), 12))
        if not reqs:
            chips.addWidget(label("No prerequisites.", "muted"))
        chips.addStretch(1)
        prereq.body.addLayout(chips)
        others = [s for s in self.skills.list() if s.id != skill.id and s.id not in {r.id for r in reqs}]
        if others:
            add = QHBoxLayout()
            combo = QComboBox()
            for s in others:
                combo.addItem(s.name, s.id)
            add.addWidget(combo)
            add.addWidget(button("Add prerequisite", "soft", "plus",
                                 lambda c=combo: self._add_prereq(skill.id, c.currentData())))
            add.addStretch(1)
            prereq.body.addLayout(add)
        self.detail.addWidget(prereq)

        for kind, title in ITEM_KINDS.items():
            card = Card(title, {"milestone": "flag", "resource": "book", "practice": "list-check"}[kind])
            items = self.skills.items(skill.id, kind)
            for it in items:
                r = QHBoxLayout()
                cb = QCheckBox(it.title)
                cb.setChecked(bool(it.done_at))
                cb.toggled.connect(lambda v, iid=it.id: self._set_done(iid, v))
                r.addWidget(cb, 1)
                if it.url:
                    r.addWidget(tool_button("external", "Open link", lambda u=it.url: QDesktopServices.openUrl(QUrl(u)), 14))
                r.addWidget(tool_button("close", "Remove", lambda iid=it.id: self._delete_item(iid), 14))
                card.body.addLayout(r)
            if items:
                done = sum(1 for it in items if it.done_at)
                card.body.addWidget(label(f"{done} of {len(items)} done", "caption"))
            add = QHBoxLayout()
            title_edit = QLineEdit()
            title_edit.setPlaceholderText({"milestone": "Next milestone", "resource": "Book, course or video",
                                           "practice": "An exercise or small project"}[kind])
            add.addWidget(title_edit, 2)
            url_edit = QLineEdit()
            url_edit.setPlaceholderText("Link (optional)")
            add.addWidget(url_edit, 1)
            add.addWidget(button("Add", "soft", "plus",
                                 lambda k=kind, t=title_edit, u=url_edit: self._add_item(skill.id, k, t, u)))
            title_edit.returnPressed.connect(lambda k=kind, t=title_edit, u=url_edit: self._add_item(skill.id, k, t, u))
            card.body.addLayout(add)
            self.detail.addWidget(card)

        log_card = Card("Activity & evidence", "chart")
        form = QHBoxLayout()
        mode = QComboBox()
        for key, text in MODES.items():
            mode.addItem(text, key)
        mode.setCurrentIndex(1)
        form.addWidget(mode)
        minutes = QSpinBox()
        minutes.setRange(0, 1440)
        minutes.setSingleStep(15)
        minutes.setSpecialValueText("No time")
        minutes.setSuffix(" min")
        minutes.setValue(30)
        form.addWidget(minutes)
        log_card.body.addLayout(form)
        note = QLineEdit()
        note.setPlaceholderText("What you did or made")
        log_card.body.addWidget(note)
        evidence = QLineEdit()
        evidence.setPlaceholderText("Link to evidence — a repo, video, document (optional)")
        log_card.body.addWidget(evidence)
        r = QHBoxLayout()
        r.addWidget(button("Log it", "primary", "check",
                           lambda: self._log(skill.id, mode.currentData(), minutes.value(), note, evidence)))
        r.addStretch(1)
        log_card.body.addLayout(r)
        for lg in self.skills.logs(skill.id, limit=12):
            row = QHBoxLayout()
            bits = [lg.date, MODE_SHORT[lg.mode]]
            if lg.minutes:
                bits.append(format_duration(lg.minutes * 60))
            if lg.note:
                bits.append(lg.note)
            row.addWidget(label(" · ".join(bits), "", wrap=True), 1)
            if lg.evidence_url:
                row.addWidget(tool_button("external", "Open evidence",
                                          lambda u=lg.evidence_url: QDesktopServices.openUrl(QUrl(u)), 14))
            row.addWidget(tool_button("close", "Delete entry", lambda lid=lg.id: self._delete_log(lid), 14))
            log_card.body.addLayout(row)
        self.detail.addWidget(log_card)

        links = Card("Linked projects, notes and tasks", "link")
        from src.repositories.links import KIND_TABLES
        from src.ui.widgets.links import LinksPanel

        kinds = [k for k in ("project", "note", "task", "course", "goal") if k in KIND_TABLES]
        links.body.addWidget(LinksPanel(self.ctx, "skill", skill.id, kinds))
        self.detail.addWidget(links)

        notes = Card("Notes", "notes")
        edit = QPlainTextEdit(skill.notes)
        edit.setPlaceholderText("Anything worth remembering")
        edit.setFixedHeight(120)
        notes.body.addWidget(edit)
        r = QHBoxLayout()
        r.addWidget(button("Save notes", "soft", "check", lambda: self._save_notes(skill.id, edit.toPlainText())))
        r.addStretch(1)
        notes.body.addLayout(r)
        self.detail.addWidget(notes)
        self.detail.addStretch(1)

    # -- actions ------------------------------------------------------------------------------
    def _changed(self) -> None:
        bus.notify("skills")
        self._fill_detail()

    def edit(self, skill) -> None:
        if SkillDialog(self, skill).exec():
            bus.notify("skills")
            self.refresh()

    def delete(self, skill) -> None:
        if confirm(self, "Delete skill?", f"“{skill.name}”, its roadmap and activity log will be deleted.") and \
                guarded(self, lambda: self.skills.delete(skill.id)):
            self.current_id = None
            bus.notify("skills")
            self.refresh()

    def _add_prereq(self, skill_id: int, requires_id) -> None:
        if requires_id is not None and guarded(self, lambda: self.skills.add_prerequisite(skill_id, int(requires_id))):
            self._changed()

    def _remove_prereq(self, skill_id: int, requires_id: int) -> None:
        if guarded(self, lambda: self.skills.remove_prerequisite(skill_id, requires_id)):
            self._changed()

    def _add_item(self, skill_id: int, kind: str, title: QLineEdit, url: QLineEdit) -> None:
        if title.text().strip() and guarded(self, lambda: self.skills.add_item(skill_id, kind, title.text(),
                                                                               url.text())):
            self._changed()

    def _set_done(self, item_id: int, done: bool) -> None:
        if guarded(self, lambda: self.skills.set_item_done(item_id, done)):
            bus.notify("skills")

    def _delete_item(self, item_id: int) -> None:
        if guarded(self, lambda: self.skills.delete_item(item_id)):
            self._changed()

    def _log(self, skill_id: int, mode: str, minutes: int, note: QLineEdit, evidence: QLineEdit) -> None:
        if guarded(self, lambda: self.skills.log(skill_id, mode, minutes or None, note.text(), evidence.text())):
            self.toast("Logged")
            self._changed()

    def _delete_log(self, log_id: int) -> None:
        if guarded(self, lambda: self.skills.delete_log(log_id)):
            self._changed()

    def _save_notes(self, skill_id: int, text: str) -> None:
        skill = self.skills.get(skill_id)
        if skill and guarded(self, lambda: self.skills.save(
                skill.id, name=skill.name, category=skill.category, baseline=skill.baseline, goal=skill.goal,
                status=skill.status, review_date=date.fromisoformat(skill.review_date) if skill.review_date else None,
                notes=text)):
            self.toast("Notes saved")

    # -- weekly review ----------------------------------------------------------------------------
    def _fill_week(self) -> None:
        clear_layout(self.week)
        start = week_start(today(), int(self.ctx.settings.get("week_start")))
        data = self.skills.week_summary(start)
        t = data["totals"]
        card = Card(f"Week of {start.strftime('%d %b')}", "chart")
        top = QHBoxLayout()
        for value, caption in ((format_duration(t["learn"] * 60) if t["learn"] else "–", "learning"),
                               (format_duration(t["practice"] * 60) if t["practice"] else "–", "practice"),
                               (format_duration(t["build"] * 60) if t["build"] else "–", "building"),
                               (str(t["evidence"]), "pieces of evidence"), (str(t["milestones"]), "milestones")):
            col = QVBoxLayout()
            col.addWidget(label(value, "metric"))
            col.addWidget(label(caption, "metricLabel"))
            top.addLayout(col)
        top.addStretch(1)
        card.body.addLayout(top)
        if not data["per_skill"]:
            card.body.addWidget(label("Nothing logged this week, and that's fine. When you do something — even ten "
                                      "minutes — log it on the skill's page.", "muted", wrap=True))
        else:
            produced = t["practice"] + t["build"]
            consumed = t["learn"]
            if consumed and produced:
                card.body.addWidget(label(f"Time spent practising or making things: {format_duration(produced * 60)}; "
                                          f"time spent taking things in: {format_duration(consumed * 60)}.", "",
                                          wrap=True))
        self.week.addWidget(card)
        names = {s.id: s.name for s in self.skills.list()}
        for sid, s in sorted(data["per_skill"].items(), key=lambda x: names.get(x[0], "")):
            c = Card(names.get(sid, "Skill"), "skill")
            bits = [f"{MODE_SHORT[m]} {format_duration(s[m] * 60)}" for m in ("learn", "practice", "build") if s[m]]
            if s["evidence"]:
                bits.append(f"{s['evidence']} evidence")
            if s["milestones"]:
                bits.append(f"{s['milestones']} milestone{'s' if s['milestones'] != 1 else ''} reached")
            c.body.addWidget(label(" · ".join(bits) or "Activity logged", "", wrap=True))
            c.body.addWidget(button("Open", "link", "chev-right", lambda i=sid: self.open_skill(i)), 0,
                             Qt.AlignmentFlag.AlignLeft)
            self.week.addWidget(c)
        due = self.skills.due_reviews()
        if due:
            c = Card("Ready for a review", "flag")
            for s in due:
                c.body.addWidget(button(f"{s.name} (review {s.review_date})", "link", on_click=lambda i=s.id: self.open_skill(i)),
                                 0, Qt.AlignmentFlag.AlignLeft)
            self.week.addWidget(c)
        self.week.addStretch(1)
