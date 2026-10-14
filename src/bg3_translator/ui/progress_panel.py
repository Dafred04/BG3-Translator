"""Detailed translation progress panel.

Показывает, что программа делает прямо сейчас: текущий мод, этапы по порядку,
текущий файл, счётчики, скорость и ETA. Все поля питаются объектами
JobProgress из асинхронного движка — никаких «фальшивых» спиннеров.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .widgets import GlowProgressBar, repolish
from ..services.engine import (
    STAGE_ICON_ACTIVE,
    STAGE_ICON_DONE,
    STAGE_ICON_PENDING,
    STAGE_ORDER,
    STAGE_TEXT,
)

_STATE_BY_ICON = {STAGE_ICON_ACTIVE: "active", STAGE_ICON_DONE: "done", STAGE_ICON_PENDING: "pending"}


def _fmt_time(seconds: float) -> str:
    """Format a duration in a compact human form."""
    if not seconds or seconds <= 0:
        return "—"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h} ч {m:02d} мин"
    if m:
        return f"{m} мин {s:02d} с"
    return f"{s} с"


class ProgressPanel(QWidget):
    """Live, human-readable view of a translation run."""

    STAGE_COLUMNS = 3

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        # --- заголовок: мод + процент ---
        head = QHBoxLayout()
        self.mod_label = QLabel("Мод: —")
        self.mod_label.setObjectName("CardTitle")
        head.addWidget(self.mod_label, 1)
        self.percent_label = QLabel("0%")
        self.percent_label.setObjectName("PercentBig")
        head.addWidget(self.percent_label)
        lay.addLayout(head)

        self.bar = GlowProgressBar(height=10)
        lay.addWidget(self.bar)

        self.stage_label = QLabel("Ожидание запуска")
        self.stage_label.setObjectName("Subtitle")
        lay.addWidget(self.stage_label)

        # --- этапы (фиксированный порядок, иконка = реальное состояние) ---
        stages = QGridLayout()
        stages.setHorizontalSpacing(8)
        stages.setVerticalSpacing(8)
        self.stage_labels: dict[str, QLabel] = {}
        for i, stage_id in enumerate(STAGE_ORDER):
            lbl = QLabel(f"{STAGE_ICON_PENDING}  {STAGE_TEXT[stage_id]}")
            lbl.setObjectName("StageChip")
            lbl.setProperty("state", "pending")
            self.stage_labels[str(stage_id.value)] = lbl
            stages.addWidget(lbl, i // self.STAGE_COLUMNS, i % self.STAGE_COLUMNS)
        for c in range(self.STAGE_COLUMNS):
            stages.setColumnStretch(c, 1)
        lay.addLayout(stages)

        # --- текущий файл ---
        self.file_label = QLabel("Файл: —")
        self.file_label.setObjectName("Subtitle")
        lay.addWidget(self.file_label)

        # --- метрики 4 x 2 ---
        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(10)
        self.line_label = self._metric(grid, 0, 0, "Строка")
        self.files_label = self._metric(grid, 0, 1, "Файлов")
        self.done_label = self._metric(grid, 0, 2, "Переведено")
        self.skip_label = self._metric(grid, 0, 3, "Пропущено")
        self.err_label = self._metric(grid, 1, 0, "Ошибок")
        self.speed_label = self._metric(grid, 1, 1, "Скорость")
        self.eta_label = self._metric(grid, 1, 2, "Осталось")
        for c in range(4):
            grid.setColumnStretch(c, 1)
        lay.addLayout(grid)

        self.reset()

    # ------------------------------------------------------------------
    @staticmethod
    def _metric(grid: QGridLayout, row: int, col: int, caption: str) -> QLabel:
        box = QVBoxLayout()
        box.setSpacing(0)
        cap = QLabel(caption)
        cap.setObjectName("StatLabel")
        val = QLabel("—")
        val.setObjectName("MetricValue")
        box.addWidget(cap)
        box.addWidget(val)
        grid.addLayout(box, row, col)
        return val

    @staticmethod
    def _set_state(widget: QLabel, key: str, value: str):
        if widget.property(key) != value:
            widget.setProperty(key, value)
            repolish(widget)

    # ------------------------------------------------------------------
    def reset(self) -> None:
        """Return the panel to its initial state."""
        self.bar.setMaximum(100)
        self.bar.setValue(0)
        self.percent_label.setText("0%")
        self.stage_label.setText("Ожидание запуска")
        self.mod_label.setText("Мод: —")
        for stage_id, lbl in zip(STAGE_ORDER, self.stage_labels.values()):
            lbl.setText(f"{STAGE_ICON_PENDING}  {STAGE_TEXT[stage_id]}")
            self._set_state(lbl, "state", "pending")
        self.file_label.setText("Файл: —")
        self.file_label.setToolTip("")
        self.line_label.setText("0 / 0")
        self.files_label.setText("0 / 0")
        self.done_label.setText("0")
        self.skip_label.setText("0")
        self.err_label.setText("0")
        self._set_state(self.err_label, "tone", "")
        self.speed_label.setText("—")
        self.eta_label.setText("—")

    def update_progress(self, pg) -> None:
        """Refresh every field from a JobProgress payload."""
        stage = getattr(pg, "stage", None)
        current = str(getattr(stage, "value", stage))
        order = [str(s.value) for s in STAGE_ORDER]

        for stage_id, lbl in zip(STAGE_ORDER, self.stage_labels.values()):
            key = str(stage_id.value)
            icon = STAGE_ICON_PENDING
            if current in order:
                if order.index(key) < order.index(current):
                    icon = STAGE_ICON_DONE
                elif key == current:
                    icon = STAGE_ICON_ACTIVE
            lbl.setText(f"{icon}  {STAGE_TEXT[stage_id]}")
            self._set_state(lbl, "state", _STATE_BY_ICON.get(icon, "pending"))

        mod = getattr(pg, "current_mod", "") or "—"
        self.mod_label.setText(f"Мод: {mod}")

        total_files = getattr(pg, "total_files", 0) or 0
        processed = getattr(pg, "processed_files", 0) or 0
        pct = getattr(pg, "percent", None)
        if pct is None:
            pct = processed / total_files * 100 if total_files else 0
        pct = max(0, min(100, int(pct)))
        self.bar.setMaximum(100)
        self.bar.setValue(pct)
        self.percent_label.setText(f"{pct}%")
        self.stage_label.setText(getattr(pg, "stage_text", "") or "")

        cur_file = getattr(pg, "current_file", "") or "—"
        self.file_label.setToolTip(cur_file)
        fm = QFontMetrics(self.file_label.font())
        width = max(self.file_label.width(), 300)
        self.file_label.setText(fm.elidedText(f"Файл: {cur_file}", Qt.TextElideMode.ElideMiddle, width))

        self.line_label.setText(f"{getattr(pg, 'current_line', 0)} / {getattr(pg, 'lines_total', 0)}")
        self.files_label.setText(f"{processed} / {total_files}")
        self.done_label.setText(str(getattr(pg, "succeeded", 0)))
        self.skip_label.setText(str(getattr(pg, "skipped", 0)))
        errors = getattr(pg, "errors", 0) or getattr(pg, "failed", 0)
        self.err_label.setText(str(errors))
        self._set_state(self.err_label, "tone", "danger" if errors else "")

        speed = getattr(pg, "speed_lines_per_sec", 0)
        self.speed_label.setText(f"{speed:g} стр/с" if speed else "—")
        self.eta_label.setText(_fmt_time(getattr(pg, "eta_seconds", 0)))
