"""Shared motion helpers.

All DayOS animation goes through here so durations, easing and the
reduced-motion switch stay consistent:

* 140–180 ms for micro-interactions (hover, press, checks, toasts)
* 220–260 ms for page and theme transitions
* ``OutCubic`` easing; nothing bounces and nothing loops forever.

Animations never block input: overlays are transparent to the mouse, and
temporary opacity effects are removed as soon as an animation finishes so they
cost nothing afterwards.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QEasingCurve, QObject, QPoint, QPropertyAnimation, QVariantAnimation, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QGraphicsOpacityEffect, QLabel, QWidget
from shiboken6 import isValid

FAST = 150
MEDIUM = 200
PAGE = 250
EASE = QEasingCurve.Type.OutCubic

_motion_enabled: Callable[[], bool] = lambda: True


def set_motion_provider(provider: Callable[[], bool]) -> None:
    """``provider`` returns False when the user (or Windows) asks for reduced motion."""
    global _motion_enabled
    _motion_enabled = provider


def motion_enabled() -> bool:
    try:
        return bool(_motion_enabled())
    except Exception:  # never let a settings problem break painting
        return True


def tween(owner: QObject, start: float, end: float, duration: int, on_value: Callable[[float], None],
          on_done: Callable[[], None] | None = None, easing: QEasingCurve.Type = EASE,
          key: str = "_tween") -> QVariantAnimation | None:
    """Animate a float and call ``on_value`` each frame. One running tween per ``key``.

    With reduced motion the final value is applied immediately.
    """
    previous = getattr(owner, key, None)
    if isinstance(previous, QVariantAnimation) and isValid(previous):
        previous.stop()
    if not motion_enabled() or duration <= 0:
        on_value(end)
        if on_done:
            on_done()
        return None
    anim = QVariantAnimation(owner)
    anim.setStartValue(float(start))
    anim.setEndValue(float(end))
    anim.setDuration(duration)
    anim.setEasingCurve(easing)
    anim.valueChanged.connect(lambda v: on_value(float(v)))
    if on_done:
        anim.finished.connect(on_done)
    setattr(owner, key, anim)
    anim.start(QVariantAnimation.DeletionPolicy.DeleteWhenStopped)
    return anim


def fade_in(widget: QWidget, duration: int = MEDIUM, rise: int = 0) -> None:
    """Fade a widget in (optionally rising a few pixels); the effect is removed afterwards."""
    if not motion_enabled() or not isValid(widget):
        return
    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(0.0)
    widget.setGraphicsEffect(effect)
    anim = QPropertyAnimation(effect, b"opacity", widget)
    anim.setDuration(duration)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(EASE)

    def done() -> None:
        if isValid(widget):
            widget.setGraphicsEffect(None)

    anim.finished.connect(done)
    anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
    if rise and widget.parentWidget() is not None and widget.parentWidget().layout() is None:
        end = widget.pos()
        move = QPropertyAnimation(widget, b"pos", widget)
        move.setDuration(duration)
        move.setStartValue(end + QPoint(0, rise))
        move.setEndValue(end)
        move.setEasingCurve(EASE)
        move.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)


def snapshot_fade(target: QWidget, duration: int = PAGE, drift: int = 0) -> None:
    """Cover ``target`` with a picture of how it looks now, then fade that picture away.

    Call *before* changing the widget (page switch, theme change). The real,
    already-updated UI underneath stays fully interactive during the fade.
    """
    if not motion_enabled() or not isValid(target) or not target.isVisible() or target.width() < 2:
        return
    pixmap: QPixmap = target.grab()
    overlay = QLabel(target)
    overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    overlay.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
    overlay.setPixmap(pixmap)
    overlay.setGeometry(0, 0, target.width(), target.height())
    overlay.show()
    overlay.raise_()
    effect = QGraphicsOpacityEffect(overlay)
    overlay.setGraphicsEffect(effect)

    def step(v: float) -> None:
        if isValid(overlay):
            effect.setOpacity(1.0 - v)
            if drift:
                overlay.move(0, int(-drift * v))

    def finish() -> None:
        if isValid(overlay):
            overlay.deleteLater()

    anim = QVariantAnimation(overlay)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setDuration(duration)
    anim.setEasingCurve(EASE)
    anim.valueChanged.connect(lambda v: step(float(v)))
    anim.finished.connect(finish)
    anim.start(QVariantAnimation.DeletionPolicy.DeleteWhenStopped)
