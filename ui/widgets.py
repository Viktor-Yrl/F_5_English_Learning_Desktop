from datetime import date

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import QCheckBox, QPushButton, QWidget

from ui.theme import COLORS


class PillSwitch(QCheckBox):
    def __init__(self):
        super().__init__()
        self.setFixedSize(56, 30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setText("")
        self.stateChanged.connect(lambda _: self.update())

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        checked = self.isChecked()
        track_color = QColor(COLORS["blue"] if checked else COLORS["panel_alt"])
        border_color = QColor(COLORS["blue"] if checked else COLORS["line"])
        knob_color = QColor("#ffffff" if checked else COLORS["muted"])

        painter.setPen(QPen(border_color, 1))
        painter.setBrush(track_color)
        painter.drawRoundedRect(1, 1, 54, 28, 14, 14)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(knob_color)
        knob_x = 29 if checked else 4
        painter.drawEllipse(knob_x, 4, 22, 22)


class StatsChartWidget(QWidget):
    SERIES = [
        ("new_learned", "New learned", "#ef6bab"),
        ("reviewed", "Reviewed", "#ffd166"),
        ("mastered", "Mastered", "#55c583"),
        ("known", "Already known", "#cfd1d4"),
    ]

    def __init__(self):
        super().__init__()
        self.days: list[str] = []
        self.data: dict[str, dict[str, int]] = {}
        self.setMinimumHeight(420)

    def set_stats(self, days: list[str], data: dict[str, dict[str, int]]) -> None:
        self.days = days
        self.data = data
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(COLORS["panel"]))

        painter.setPen(QColor(COLORS["text"]))
        painter.setFont(self.font())
        painter.drawText(18, 18, self.width() - 36, 24, Qt.AlignmentFlag.AlignLeft, "Activity over time")

        left, top, right, bottom = 64, 56, 30, 112
        width = max(1, self.width() - left - right)
        height = max(1, self.height() - top - bottom)
        plot_left = left
        plot_top = top
        plot_bottom = top + height

        totals = [
            sum(self.data.get(day, {}).get(key, 0) for key, _, _ in self.SERIES)
            for day in self.days
        ]
        max_value = max(totals + [10])
        step = 15 if max_value <= 120 else max(25, ((max_value // 8 + 24) // 25) * 25)
        chart_max = max(step * 8, ((max_value + step - 1) // step) * step)

        grid_pen = QPen(QColor("#464a54"))
        grid_pen.setWidth(1)
        painter.setPen(grid_pen)
        label_color = QColor("#cfd3dc")
        for i in range(9):
            value = chart_max * i // 8
            y = plot_bottom - int(height * (value / chart_max))
            painter.drawLine(plot_left, y, plot_left + width, y)
            painter.setPen(label_color if i % 2 == 0 else QColor("#8f96a5"))
            if i % 2 == 0 or i == 0:
                painter.drawText(8, y - 9, 48, 18, Qt.AlignmentFlag.AlignRight, str(value))
            painter.setPen(grid_pen)

        if not self.days:
            painter.setPen(label_color)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No statistics yet")
            return

        slot = width / max(1, len(self.days))
        bar_width = max(3, min(46, int(slot * 0.48)))
        label_step = self.day_label_step(slot)
        for index, day in enumerate(self.days):
            x = int(plot_left + slot * index + (slot - bar_width) / 2)
            y_cursor = plot_bottom
            for key, _, color in self.SERIES:
                value = self.data.get(day, {}).get(key, 0)
                if value <= 0:
                    continue
                bar_h = max(2, int(height * value / chart_max))
                y_cursor -= bar_h
                painter.fillRect(x, y_cursor, bar_width, bar_h, QColor(color))
                if bar_h > 18:
                    painter.setPen(QColor("#333333"))
                    painter.drawText(x, y_cursor + 2, bar_width, 18, Qt.AlignmentFlag.AlignCenter, str(value))

            should_draw_label = index == 0 or index == len(self.days) - 1 or index % label_step == 0
            if should_draw_label:
                painter.setPen(label_color)
                painter.drawText(
                    int(plot_left + slot * index - 26),
                    plot_bottom + 12,
                    56,
                    28,
                    Qt.AlignmentFlag.AlignCenter,
                    self.format_day_label(day),
                )

        legend_y = self.height() - 42
        legend_width = 160
        start_x = max(left, int((self.width() - legend_width * len(self.SERIES)) / 2))
        for index, (_, title, color) in enumerate(self.SERIES):
            x = start_x + index * legend_width
            painter.fillRect(x, legend_y + 4, 12, 12, QColor(color))
            painter.setPen(QColor(COLORS["muted"]))
            painter.drawText(x + 20, legend_y, legend_width - 22, 22, Qt.AlignmentFlag.AlignLeft, title)

    def format_day_label(self, value: str) -> str:
        try:
            current = date.fromisoformat(value)
        except ValueError:
            return value
        if current == date.today():
            return "Today"
        return current.strftime("%d %b")

    def day_label_step(self, slot_width: float) -> int:
        min_label_width = 58
        if slot_width >= min_label_width:
            return 1
        return max(2, int(min_label_width / max(1, slot_width)) + 1)


class PlayButton(QPushButton):
    def __init__(self):
        super().__init__("")
        self.setFixedSize(42, 42)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("background: transparent; border: 0;")

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pressed = self.isDown()
        painter.setPen(QPen(QColor("#4d5f94"), 1.2))
        painter.setBrush(QColor("#6d8cff" if pressed else "#222631"))
        painter.drawRoundedRect(QRectF(1, 1, self.width() - 2, self.height() - 2), 10, 10)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#ffffff" if pressed else "#6d8cff"))
        triangle = QPolygonF([
            QPointF(17, 13),
            QPointF(17, 29),
            QPointF(29, 21),
        ])
        painter.drawPolygon(triangle)


class EyeRevealButton(QPushButton):
    def __init__(self):
        super().__init__("")
        self.setFixedSize(42, 42)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Show mnemonic image, translation and examples")
        self.setStyleSheet("background: transparent; border: 0;")

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pressed = self.isDown()
        hovered = self.underMouse()
        bg = "#6d8cff" if pressed else "#263251" if hovered else "#1b1e25"
        border = "#6d8cff" if hovered or pressed else "#343946"
        text_color = "#ffffff" if pressed else "#8fa6ff"
        painter.setPen(QPen(QColor(border), 1.2))
        painter.setBrush(QColor(bg))
        painter.drawRoundedRect(QRectF(1, 1, self.width() - 2, self.height() - 2), 10, 10)

        painter.setPen(QPen(QColor(text_color), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QRectF(10, 14, 22, 14))
        painter.setBrush(QColor(text_color))
        painter.drawEllipse(QRectF(19, 19, 4, 4))


class SidebarIcon(QWidget):
    def __init__(self, kind: str):
        super().__init__()
        self.kind = kind
        self.selected = False
        self.setFixedSize(38, 38)

    def set_selected(self, selected: bool) -> None:
        self.selected = selected
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(self.width() / 46, self.height() / 46)
        color = QColor(COLORS["blue"] if self.selected else COLORS["muted"])
        pen = QPen(color, 2.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        if self.kind == "logo":
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(COLORS["blue"]))
            painter.drawRoundedRect(QRectF(5, 5, 36, 36), 8, 8)
            painter.setPen(QPen(QColor("#ffffff"), 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.drawLine(16, 16, 22, 20)
            painter.drawLine(16, 16, 16, 30)
            painter.drawLine(16, 30, 22, 33)
            painter.drawLine(30, 16, 24, 20)
            painter.drawLine(30, 16, 30, 30)
            painter.drawLine(30, 30, 24, 33)
            painter.drawLine(23, 20, 23, 33)
            return

        if self.kind == "folder":
            painter.drawLine(8, 17, 18, 17)
            painter.drawLine(18, 17, 22, 21)
            painter.drawLine(22, 21, 38, 21)
            painter.drawLine(38, 21, 38, 34)
            painter.drawLine(38, 34, 8, 34)
            painter.drawLine(8, 34, 8, 17)
        elif self.kind == "search":
            painter.drawEllipse(QRectF(11, 11, 18, 18))
            painter.drawLine(27, 27, 37, 37)
        elif self.kind == "study":
            painter.drawLine(8, 20, 23, 13)
            painter.drawLine(23, 13, 38, 20)
            painter.drawLine(38, 20, 23, 27)
            painter.drawLine(23, 27, 8, 20)
            painter.drawLine(15, 25, 15, 32)
            painter.drawLine(15, 32, 23, 36)
            painter.drawLine(23, 36, 31, 32)
            painter.drawLine(31, 32, 31, 25)
        elif self.kind == "stats":
            painter.drawRoundedRect(QRectF(10, 27, 5, 9), 2, 2)
            painter.drawRoundedRect(QRectF(20, 20, 5, 16), 2, 2)
            painter.drawRoundedRect(QRectF(30, 12, 5, 24), 2, 2)
        elif self.kind == "rules":
            painter.drawRoundedRect(QRectF(12, 9, 24, 30), 3, 3)
            painter.drawLine(17, 18, 31, 18)
            painter.drawLine(17, 25, 31, 25)
            painter.drawLine(17, 32, 27, 32)
        elif self.kind == "book":
            painter.drawLine(23, 16, 23, 35)
            painter.drawLine(23, 18, 14, 15)
            painter.drawLine(14, 15, 9, 17)
            painter.drawLine(9, 17, 9, 33)
            painter.drawLine(9, 33, 14, 31)
            painter.drawLine(14, 31, 23, 35)
            painter.drawLine(23, 18, 32, 15)
            painter.drawLine(32, 15, 37, 17)
            painter.drawLine(37, 17, 37, 33)
            painter.drawLine(37, 33, 32, 31)
            painter.drawLine(32, 31, 23, 35)
        elif self.kind == "info":
            painter.drawEllipse(QRectF(12, 10, 22, 22))
            painter.drawLine(23, 20, 23, 28)
            painter.drawPoint(23, 15)
        elif self.kind == "settings":
            painter.drawEllipse(QRectF(18, 18, 10, 10))
            painter.drawEllipse(QRectF(12, 12, 22, 22))
            for x1, y1, x2, y2 in [(23, 7, 23, 12), (23, 34, 23, 39), (7, 23, 12, 23), (34, 23, 39, 23), (12, 12, 15, 15), (31, 31, 34, 34), (34, 12, 31, 15), (15, 31, 12, 34)]:
                painter.drawLine(x1, y1, x2, y2)
