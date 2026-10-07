"""VRGB Suite: widgets."""

import math
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal, QPointF
from PyQt6.QtGui import (
    QColor,
    QConicalGradient,
    QRadialGradient,
    QPainter,
    QPen,
    QBrush,
    QIcon,
    QPixmap,
)
from PyQt6.QtWidgets import QWidget, QSizePolicy


# ----------------------------------------------------------------------------
# HS color wheel widget
# ----------------------------------------------------------------------------

class ColorWheel(QWidget):
    """Hue/Saturation wheel. Value (lightness) is supplied externally."""

    hs_changed = pyqtSignal(float, float)   # hue 0..1, saturation 0..1
    released = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._h = 0.0
        self._s = 0.0
        self._value = 1.0
        self.setMinimumSize(220, 220)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_hsv(self, h, s, v):
        self._h, self._s, self._value = h, s, v
        self.update()

    def set_value(self, v):
        self._value = v
        self.update()

    def _geom(self):
        side = min(self.width(), self.height()) - 8
        cx = self.width() / 2.0
        cy = self.height() / 2.0
        return cx, cy, side / 2.0

    def paintEvent(self, _evt):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy, r = self._geom()
        if r <= 0:
            return
        center = QPointF(cx, cy)

        hue_grad = QConicalGradient(center, 0.0)
        for i in range(0, 361, 30):
            hue_grad.setColorAt(i / 360.0, QColor.fromHsvF((i % 360) / 360.0, 1.0, 1.0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(hue_grad))
        p.drawEllipse(center, r, r)

        sat_grad = QRadialGradient(center, r)
        sat_grad.setColorAt(0.0, QColor(255, 255, 255, 255))
        sat_grad.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setBrush(QBrush(sat_grad))
        p.drawEllipse(center, r, r)

        if self._value < 1.0:
            shade = int((1.0 - self._value) * 255)
            p.setBrush(QColor(0, 0, 0, shade))
            p.drawEllipse(center, r, r)

        angle = self._h * 2.0 * math.pi
        dist = self._s * r
        mx = cx + dist * math.cos(angle)
        my = cy - dist * math.sin(angle)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(0, 0, 0, 200), 3))
        p.drawEllipse(QPointF(mx, my), 8, 8)
        p.setPen(QPen(QColor(255, 255, 255, 230), 1.5))
        p.drawEllipse(QPointF(mx, my), 8, 8)

    def _pick(self, pos):
        cx, cy, r = self._geom()
        if r <= 0:
            return
        dx = pos.x() - cx
        dy = cy - pos.y()
        dist = math.hypot(dx, dy)
        self._s = min(1.0, dist / r)
        ang = math.atan2(dy, dx)
        if ang < 0:
            ang += 2.0 * math.pi
        self._h = ang / (2.0 * math.pi)
        self.update()
        self.hs_changed.emit(self._h, self._s)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._pick(e.position())

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.MouseButton.LeftButton:
            self._pick(e.position())

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.released.emit()


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

PRESETS = [
    ("Red", "ff0000"), ("Orange", "ff6a00"), ("Yellow", "ffd400"),
    ("Green", "00ff44"), ("Cyan", "00e5ff"), ("Blue", "0066ff"),
    ("Purple", "aa00ff"), ("Magenta", "ff00aa"), ("White", "ffffff"),
]


def make_logo_icon():
    # Prefer VRGB's bundled application icon so the window and tray always use
    # the canonical branding. Fall back to the desktop icon theme if needed.
    cand = Path(__file__).resolve().parents[1] / "data" / "vrgb.png"
    if cand.exists():
        ic = QIcon(str(cand))
        if not ic.isNull():
            return ic
    ic = QIcon.fromTheme("vrgb")
    if not ic.isNull():
        return ic
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    grad = QConicalGradient(32, 32, 0)
    for i in range(0, 361, 30):
        grad.setColorAt(i / 360.0, QColor.fromHsvF((i % 360) / 360.0, 1.0, 1.0))
    p.setPen(QPen(QBrush(grad), 10))
    p.drawEllipse(10, 10, 44, 44)
    p.end()
    return QIcon(pm)


def swatch_icon(hexc):
    pm = QPixmap(16, 16)
    pm.fill(QColor("#" + hexc))
    return QIcon(pm)


