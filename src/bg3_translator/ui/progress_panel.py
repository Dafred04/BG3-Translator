"""Detailed translation progress panel.

Shows exactly what the program is doing right now: current mod, ordered stage
list, current file, counters, speed and ETA. All fields are driven by
JobProgress objects from the async engine, so the display always reflects the
real state of the run (never a fake spinner).
"""

from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget

from ..services.engine import (
    STAGE_ICON_ACTIVE,
    STAGE_ICON_DONE,
    STAGE_ICON_PENDING,
    STAGE_ORDER,
    STAGE_TEXT,
    StageId,
)


def _fmt_time(seconds: float) -> str:
    """Format a duration in a compact human form."""
    if seconds <= 0:
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

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        head = QHBoxLayout()
        self.mod_label = QLabel("Мод: —")
        self.mod_label.setObjectName("Title")
        head.addWidget(self.mod_label, 1)
        self.percent_label = QLabel("0%")
        self.percent_label.setObjectName("Title")
        head.addWidget(self.percent_label)
        lay.addLayout(head)

        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        lay.addWidget(self.bar)

        self.stage_label = QLabel("Ожидание запуска")
        self.stage_label.setObjectName("Subtitle")
        lay.addWidget(self.stage_label)

        # Stage checklist — fixed order, icon shows the real state.
        self.stage_labels: dict[str, QLabel] = {}
        for stage_id in STAGE_ORDER:
            lbl = QLabel(f"{STAGE_ICON_PENDING}  {STAGE_TEXT[stage_id]}")
            lbl.setObjectName("Subtitle")
            self.stage_labels[str(stage_id.value)] = lbl
            lay.addWidget(lbl)

        grid = QGridLayout()
        grid.setContentsMargins(0, 6, 0, 0)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(6)

        self.file_label = QLabel("Файл: —")
        self.line_label = QLabel("Строка: 0 / 0")
        self.files_label = QLabel("Файлов: 0 / 0")
        self.done_label = QLabel("Переведено: 0")
        self.skip_label = QLabel("Пропущено: 0")
        self.err_label = QLabel("Ошибок: 0")
        self.speed_label = QLabel("Скорость: —")
        self.eta_label = QLabel("Осталось: —")

        grid.addWidget(self.file_label, 0, 0, 1, 2)

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
        self.file_label.setText("Файл: —")
        self.line_label.setText("Строка: 0 / 0")
        self.files_label.setText("Файлов: 0 / 0")
        self.done_label.setText("Переведено: 0")
        self.skip_label.setText("Пропущено: 0")
        self.err_label.setText("Ошибок: 0")
        self.speed_label.setText("Скорость: —")
        self.eta_label.setText("Осталось: —")

    def update_progress(self, pg) -> None:
        """Refresh every field from a JobProgress payload."""
        current = str(getattr(pg, "stage", ""))
        order = [str(s.value) for s in STAGE_ORDER]

        for stage_id, lbl in zip(STAGE_ORDER, self.stage_labels.values()):
            key = str(stage_id.value)
            icon = STAGE_ICON_PENDING
            if current in order and key in order:
                if order.index(key) < order.index(current):
                    icon = STAGE_ICON_DONE
                elif key == current:
                    icon = STAGE_ICON_ACTIVE
            lbl.setText(f"{icon}  {STAGE_TEXT[stage_id]}")

        mod = getattr(pg, "current_mod", "") or "—"
        self.mod_label.setText(f"Мод: {mod}")

        total_files = max(getattr(pg, "total_files", 0), 1)
        self.bar.setMaximum(total_files)
        self.bar.setValue(getattr(pg, "processed_files", 0))
        self.percent_label.setText(f"{getattr(pg, 'percent', 0)}%")
        self.stage_label.setText(getattr(pg, "stage_text", ""))

        cur_file = getattr(pg, "current_file", "") or "—"
        self.file_label.setText(f"Файл: {cur_file}")
        self.line_label.setText(
            f"Строка: {getattr(pg, 'current_line', 0)} / {getattr(pg, 'lines_total', 0)}"
        )
        self.files_label.setText(
            f"Файлов: {getattr(pg, 'processed_files', 0)} / {getattr(pg, 'total_files', 0)}"
        )
        self.done_label.setText(f"Переведено: {getattr(pg, 'succeeded', 0)}")
        self.skip_label.setText(f"Пропущено: {getattr(pg, 'skipped', 0)}")
        errors = getattr(pg, "errors", 0) or getattr(pg, "failed", 0)
        self.err_label.setText(f"Ошибок: {errors}")

        speed = getattr(pg, "speed_lines_per_sec", 0)
        self.speed_label.setText(f"Скорость: {speed:g} строк/с" if speed else "Скорость: —")
        self.eta_label.setText(f"Осталось: {_fmt_time(getattr(pg, 'eta_seconds', 0))}")

        grid.addWidget(self.line_label, 1, 0)
        grid.addWidget(self.files_label, 1, 1)
        grid.addWidget(self.done_label, 2, 0)
        grid.addWidget(self.skip_label, 2, 1)
        grid.addWidget(self.err_label, 3, 0)
        grid.addWidget(self.speed_label, 3, 1)
        grid.addWidget(self.eta_label, 4, 0)
        lay.addLayout(grid)

        lay.addStretch(1)
