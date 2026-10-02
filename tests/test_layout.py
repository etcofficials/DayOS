"""Layout robustness: nothing may be squeezed on top of anything else, at any window size the app allows.

The window can be made as small as 980×640, which is narrower than several pages need. These
tests pin the fixes: pages scroll instead of overlapping, rows wrap, list rows are tall enough
for their text, and the sidebar folds to icons in a narrow window.
"""

import os
import unittest
from datetime import datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QRect, QSize, QTimer  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QAbstractButton,
    QApplication,
    QComboBox,
    QGridLayout,
    QLabel,
    QListWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from tests.helpers import TempHomeTestCase  # noqa: E402

app = QApplication.instance() or QApplication([])


def pump(ms: int = 30) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


class WidgetTests(unittest.TestCase):
    def test_flow_layout_keeps_one_line_with_stretch_and_wraps_when_narrow(self):
        from src.ui.widgets.common import FlowLayout

        host = QWidget()
        flow = FlowLayout(host, spacing=10)
        a, b, c = QWidget(), QWidget(), QWidget()  # plain widgets: no stylesheet can resize them
        for w in (a, b, c):
            w.setFixedSize(100, 30)
        flow.addWidget(a)
        flow.add_stretch()
        flow.addWidget(b)
        flow.addWidget(c)
        flow.setGeometry(QRect(0, 0, 600, 30))
        self.assertEqual(a.geometry().x(), 0)
        self.assertEqual(c.geometry().right(), 599)  # the stretch pushes the rest to the right end
        self.assertEqual(b.geometry().y(), a.geometry().y())
        self.assertEqual(flow.heightForWidth(600), 30)
        flow.setGeometry(QRect(0, 0, 230, 80))
        self.assertEqual(flow.heightForWidth(230), 70)  # two lines of 30 plus spacing
        self.assertGreater(c.geometry().y(), a.geometry().y())
        rects = [w.geometry() for w in (a, b, c)]
        for i, r in enumerate(rects):
            for other in rects[i + 1:]:
                self.assertFalse(r.intersects(other))
        self.assertLessEqual(flow.minimumSize().width(), 100)

    def test_segment_buttons_never_shrink_below_their_text(self):
        from src.ui.widgets.common import SegmentBar

        bar = SegmentBar([("a", "Favourites"), ("b", "Templates")])
        for b in bar.findChildren(QAbstractButton):
            self.assertEqual(b.sizePolicy().horizontalPolicy().name, "Fixed")

    def test_responsive_grid_only_uses_columns_its_cards_fit_in(self):
        from src.ui.widgets.common import ResponsiveGrid

        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(0, 0, 0, 0)
        grid = ResponsiveGrid((0, 0))
        lay.addWidget(grid)
        cards = [QWidget() for _ in range(3)]
        for card in cards:
            card.setMinimumWidth(220)
            grid.add(card)
        self.assertEqual(grid.minimumSizeHint().width(), 220)
        host.resize(400, 300)
        host.show()
        pump()
        self.assertEqual(grid._columns, 1)
        host.resize(800, 300)
        pump()
        self.assertEqual(grid._columns, 3)
        host.close()

    def test_elided_label_never_demands_its_full_width(self):
        from src.ui.widgets.common import ElidedLabel

        lbl = ElidedLabel("A very long title that would otherwise push its row wider than the list")
        self.assertLess(lbl.minimumSizeHint().width(), 40)
        self.assertGreater(lbl.sizeHint().width(), 200)


class PageLayoutTests(TempHomeTestCase):
    now = datetime.now().replace(microsecond=0)  # the demo records are dated from the real today

    def setUp(self):
        super().setUp()
        from src.ui.main_window import MainWindow
        from src.ui.theme import theme
        from tools.demo_data import fill

        theme.set_asset_dir(self.paths.cache_dir)
        theme.apply("paper")
        self.ctx.settings.set("capture.global", False)
        self.ctx.settings.set("backup.auto", "off")
        fill(self.ctx)
        from src.modules import load_features, registry

        load_features()
        self.ctx.settings.set("nav.modules", [m.key for m in registry.MODULES])
        self.window = MainWindow(self.ctx)
        self.window.resize(1300, 860)
        self.window.show()
        pump(30)

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        pump(20)
        super().tearDown()

    def _problems(self, key: str) -> list[str]:
        from src.ui.theme import LIST_ITEM_PADDING
        from src.ui.widgets.common import SegmentBar

        page = self.window.page(key)
        found = []
        frame = page.page_frame
        if frame.horizontalScrollBar().maximum() > 0:
            found.append(f"{key}: wider than the window by {frame.horizontalScrollBar().maximum()}px")
        for bar in page.findChildren(SegmentBar):
            if not bar.isVisibleTo(page):
                continue
            for b in bar.findChildren(QAbstractButton):
                if b.width() < b.sizeHint().width() - 1:
                    found.append(f"{key}: segment '{b.text()}' squeezed to {b.width()} < {b.sizeHint().width()}")
        for lw in page.findChildren(QListWidget):
            if not lw.isVisibleTo(page):
                continue
            for i in range(lw.count()):
                item = lw.item(i)
                w = lw.itemWidget(item)
                if w is None:
                    continue
                # the stylesheet pads the row top and bottom; the widget sits inside that
                need = max(w.sizeHint().height(), w.minimumSizeHint().height()) + 2 * LIST_ITEM_PADDING[1]
                if lw.visualItemRect(item).height() < need:
                    found.append(f"{key}: list row {i} is {lw.visualItemRect(item).height()}px, needs {need}")
        for child in page.findChildren(QWidget):
            lay = child.layout()
            if lay is None or not child.isVisibleTo(page):
                continue
            kids = [c for c in child.children() if isinstance(c, QWidget) and c.isVisibleTo(page)
                    and lay.indexOf(c) >= 0 and c.width() > 2 and c.height() > 2]
            for i, a in enumerate(kids):
                for b in kids[i + 1:]:
                    if isinstance(lay, QGridLayout) and (lay.getItemPosition(lay.indexOf(a))[:2]
                                                         == lay.getItemPosition(lay.indexOf(b))[:2]):
                        continue  # stacked in one cell on purpose (e.g. the timer ring and its readout)
                    inter = a.geometry().intersected(b.geometry())
                    if inter.width() > 2 and inter.height() > 2:
                        found.append(f"{key}: {type(a).__name__} overlaps {type(b).__name__} in {type(child).__name__}")
        for combo in page.findChildren(QComboBox):
            if combo.isVisibleTo(page) and combo.height() < combo.minimumSizeHint().height() - 2:
                found.append(f"{key}: combo squashed to {combo.height()}px")
        for lbl in page.findChildren(QLabel):
            # (a collapsed section shrinks to zero height instead of hiding, so check what's on screen)
            if lbl.isVisibleTo(page) and not lbl.visibleRegion().isEmpty() and lbl.wordWrap() and lbl.text() \
                    and lbl.width() > 20:
                if lbl.heightForWidth(lbl.width()) > lbl.height() + 2:
                    found.append(f"{key}: wrapped text cut off: {lbl.text()[:40]!r}")
        return found

    def _visit_all(self) -> list[str]:
        from src.modules import registry

        problems = []
        for spec in registry.MODULES:
            self.window.navigate(spec.key)
            pump(60)
            problems += self._problems(spec.key)
            page = self.window.page(spec.key)
            for tabs in page.findChildren(QTabWidget):
                if not tabs.isVisibleTo(page):
                    continue
                for index in range(1, tabs.count()):
                    tabs.setCurrentIndex(index)
                    pump(40)
                    problems += [f"{p} [{tabs.tabText(index)}]" for p in self._problems(spec.key)]
                tabs.setCurrentIndex(0)
        self.window.navigate("settings")
        settings = self.window.page("settings")
        for section in list(settings.section_buttons):
            settings.show_section(section, animate=False)
            pump(40)
            problems += [f"{p} [{section}]" for p in self._problems("settings")]
        return problems

    def test_every_page_fits_the_smallest_window_without_overlaps(self):
        self.window.resize(self.window.minimumSize())
        pump(60)
        self.assertEqual(self.window.size(), QSize(980, 640))
        self.assertTrue(self.window._collapsed)  # folded to icons to give the pages room
        self.assert_clean(self._visit_all())

    def test_every_page_lays_out_cleanly_at_the_default_size_with_large_text(self):
        self.ctx.settings.set("font_scale", 1.25)
        self.window.resize(1260, 820)
        pump(60)
        self.assertFalse(self.window._collapsed)
        self.assert_clean(self._visit_all())

    def assert_clean(self, problems: list[str]) -> None:
        if problems:
            self.fail("\n" + "\n".join(problems))

    def test_narrow_window_folds_the_sidebar_without_changing_the_saved_choice(self):
        self.assertFalse(self.window._collapsed)
        self.window.resize(1000, 700)
        pump(30)
        self.assertTrue(self.window._collapsed)
        self.assertFalse(self.ctx.settings.get("sidebar_collapsed"))
        self.window.resize(1300, 860)
        pump(30)
        self.assertFalse(self.window._collapsed)
        # expanding it by hand in a narrow window sticks, and is remembered
        self.window.resize(1000, 700)
        pump(30)
        self.window.toggle_sidebar()
        self.window.resize(1050, 700)
        pump(30)
        self.assertFalse(self.window._collapsed)
        self.assertFalse(self.ctx.settings.get("sidebar_collapsed"))
        # a sidebar the user collapsed stays collapsed when the window widens
        self.window.toggle_sidebar()
        self.window.resize(1300, 860)
        pump(30)
        self.assertTrue(self.window._collapsed)
        self.assertTrue(self.ctx.settings.get("sidebar_collapsed"))

    def test_focus_mode_folds_the_sidebar_only_for_as_long_as_it_lasts(self):
        study = self.window.page("study")
        self.window.navigate("study")
        study.toggle_focus_mode(True)
        self.assertTrue(self.window._collapsed)
        self.assertFalse(self.ctx.settings.get("sidebar_collapsed"))
        study.toggle_focus_mode(False)
        self.assertFalse(self.window._collapsed)
        self.assertFalse(self.ctx.settings.get("sidebar_collapsed"))

    def test_pages_live_in_scroll_frames_and_navigation_still_works(self):
        for key in ("today", "tasks", "notes", "settings"):
            self.window.navigate(key)
            pump(20)
            self.assertIs(self.window.current_page(), self.window.page(key))
            self.assertIs(self.window.stack.currentWidget(), self.window.page(key).page_frame)


if __name__ == "__main__":
    unittest.main()
