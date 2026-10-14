"""Dashboard: hero с drag&drop, прогресс проекта, шаги работы."""

from __future__ import annotations

from PySide6.QtCore import Qt, QThread
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from ..state import get_app_state
from ..widgets import (
    Card, DropZone, GhostButton, GlowProgressBar, HeroCard, PrimaryButton,
    RingProgress, StatTile, repolish,
)
from ...config import SUPPORTED_LANGUAGES


class StepItem(QWidget):
    """Один шаг сценария: кружок (номер / ✔) + заголовок + пояснение."""

    def __init__(self, number: int, title: str, text: str, parent=None):
        super().__init__(parent)
        self.number = number
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        self.dot = QLabel(str(number))
        self.dot.setObjectName("StepDot")
        self.dot.setFixedSize(36, 36)
        self.dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.dot.setProperty("state", "todo")
        lay.addWidget(self.dot, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(2)
        t = QLabel(title)
        t.setObjectName("CardTitle")
        d = QLabel(text)
        d.setObjectName("Subtitle")
        d.setWordWrap(True)
        col.addWidget(t)
        col.addWidget(d)
        lay.addLayout(col, 1)

    def set_state(self, state: str):
        """state: todo | current | done"""
        self.dot.setText("✔" if state == "done" else str(self.number))
        if self.dot.property("state") != state:
            self.dot.setProperty("state", state)
            repolish(self.dot)


class DashboardPage(QWidget):
    """Landing page: open mod, see progress, quick actions."""

    def __init__(self, main_window):
        super().__init__()
        self.main = main_window
        self.state = get_app_state()
        self._busy = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        outer.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)

        lay = QVBoxLayout(body)
        lay.setContentsMargins(32, 28, 32, 28)
        lay.setSpacing(18)

        header = QLabel("Главная")
        header.setObjectName("PageTitle")
        lay.addWidget(header)

        # ---------------- Hero ----------------
        hero = HeroCard()
        hero.setMinimumHeight(230)
        hl = QHBoxLayout(hero)
        hl.setContentsMargins(32, 28, 32, 28)
        hl.setSpacing(32)

        left = QVBoxLayout()
        left.setSpacing(8)
        title = QLabel("Переведите мод за пару минут")
        title.setObjectName("HeroTitle")
        title.setWordWrap(True)
        text = QLabel("Откройте мод — программа найдёт все тексты, переведёт их с помощью ИИ "
                      "и соберёт готовый пакет для игры.")
        text.setObjectName("HeroText")
        text.setWordWrap(True)
        left.addWidget(title)
        left.addWidget(text)
        left.addSpacing(10)

        lang_row = QHBoxLayout()
        lang_row.setSpacing(10)
        self.source_lang = QComboBox()
        self.target_lang = QComboBox()
        for lang in SUPPORTED_LANGUAGES:
            label = f"{lang.flag_emoji}  {lang.native_name}"
            self.source_lang.addItem(label, lang.code)
            self.target_lang.addItem(label, lang.code)
        self._select(self.source_lang, "en", 0)
        self._select(self.target_lang, "ru", 0)
        swap = QPushButton("⇄")
        swap.setObjectName("Ghost")
        swap.setFixedSize(38, 38)
        swap.setToolTip("Поменять языки местами")
        swap.setCursor(Qt.CursorShape.PointingHandCursor)
        swap.clicked.connect(self._swap_langs)
        for w in (self.source_lang, swap, self.target_lang):
            lang_row.addWidget(w)
        lang_row.addStretch(1)
        left.addLayout(lang_row)

        btns = QHBoxLayout()
        btns.setSpacing(10)
        self.open_btn = PrimaryButton("Открыть файл мода…")
        self.open_btn.clicked.connect(self._open_mod)
        self.open_folder_btn = GhostButton("Открыть папку…")
        self.open_folder_btn.clicked.connect(self._open_folder)
        btns.addWidget(self.open_btn)
        btns.addWidget(self.open_folder_btn)
        btns.addStretch(1)
        left.addLayout(btns)
        left.addStretch(1)
        hl.addLayout(left, 3)

        right = QVBoxLayout()
        self.drop = DropZone()
        self.drop.clicked.connect(self._open_mod)
        self.drop.dropped.connect(self._start_import)
        right.addWidget(self.drop, 1)
        self.busy_bar = GlowProgressBar(height=6)
        self.busy_bar.setMaximum(0)          # бесконечный режим
        self.busy_bar.setVisible(False)
        right.addWidget(self.busy_bar)
        hl.addLayout(right, 2)
        lay.addWidget(hero)

        # ---------------- Stats ----------------
        stats = QHBoxLayout()
        stats.setSpacing(16)
        ring_card = Card()
        rc = QHBoxLayout(ring_card)
        rc.setContentsMargins(20, 16, 24, 16)
        rc.setSpacing(18)
        self.ring = RingProgress(132)
        rc.addWidget(self.ring)
        ring_txt = QVBoxLayout()
        ring_txt.addStretch(1)
        rt = QLabel("Общий прогресс")
        rt.setObjectName("CardTitle")
        self.ring_hint = QLabel("Пока нет проекта")
        self.ring_hint.setObjectName("Subtitle")
        self.ring_hint.setWordWrap(True)
        ring_txt.addWidget(rt)
        ring_txt.addWidget(self.ring_hint)
        ring_txt.addStretch(1)
        rc.addLayout(ring_txt)
        stats.addWidget(ring_card, 2)

        self.stat_total = StatTile("Всего строк", tone="accent")
        self.stat_translated = StatTile("Переведено", tone="success")
        self.stat_errors = StatTile("Ошибок проверки", tone="danger")
        for tile in (self.stat_total, self.stat_translated, self.stat_errors):
            stats.addWidget(tile, 1)
        lay.addLayout(stats)

        # ---------------- Steps + Project ----------------
        bottom = QHBoxLayout()
        bottom.setSpacing(16)

        steps_card = Card()
        sl = QVBoxLayout(steps_card)
        sl.setContentsMargins(24, 20, 24, 20)
        sl.setSpacing(16)
        st = QLabel("Как это работает")
        st.setObjectName("Title")
        sl.addWidget(st)
        self.steps = [
            StepItem(1, "Откройте мод", "Файл .pak, .zip, .xml или распакованная папка."),
            StepItem(2, "Переведите", "Одна кнопка на вкладке «Перевод» — ИИ и словарь сделают всё сами."),
            StepItem(3, "Проверьте и экспортируйте", "Поправьте строки при желании и сохраните готовый .pak."),
        ]
        for s in self.steps:
            sl.addWidget(s)
        sl.addStretch(1)
        bottom.addWidget(steps_card, 3)

        proj_card = Card()
        pl = QVBoxLayout(proj_card)
        pl.setContentsMargins(24, 20, 24, 20)
        pl.setSpacing(8)
        pt = QLabel("Текущий проект")
        pt.setObjectName("Title")
        pl.addWidget(pt)
        self.project_info = QLabel("")
        self.project_info.setObjectName("Subtitle")
        self.project_info.setWordWrap(True)
        pl.addWidget(self.project_info)
        pl.addStretch(1)
        self.continue_btn = PrimaryButton("Продолжить перевод")
        self.continue_btn.clicked.connect(lambda: self.main.navigate("editor"))
        pl.addWidget(self.continue_btn)
        bottom.addWidget(proj_card, 2)
        lay.addLayout(bottom)
        lay.addStretch(1)

        self.state.project_changed.connect(self.refresh)
        self.state.entry_edited.connect(lambda _h: self.refresh())
        self.refresh(animate=False)

    # ------------------------------------------------------------------
    @staticmethod
    def _select(box: QComboBox, code: str, fallback: int):
        idx = box.findData(code)
        box.setCurrentIndex(idx if idx >= 0 else fallback)

    def _swap_langs(self):
        a, b = self.source_lang.currentIndex(), self.target_lang.currentIndex()
        self.source_lang.setCurrentIndex(b)
        self.target_lang.setCurrentIndex(a)

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()

    def refresh(self, *_args, animate: bool = True):
        s = self.state.stats()
        self.stat_total.set_value(str(s["total"]), animate)
        self.stat_translated.set_value(str(s["translated"]), animate)
        self.stat_errors.set_value(str(s["errors"]), animate)
        self.ring.set_value(s["percent"])

        project = self.state.project
        if project:
            m = project.metadata
            author = m.author or "автор неизвестен"
            self.project_info.setText(f"{m.name}\n{author} · версия {m.version}\n{m.source_path}")
            self.ring_hint.setText(f"Переведено {s['translated']} из {s['total']} строк.")
        else:
            self.project_info.setText("Проект не загружен.\nПеретащите мод в рамку выше или нажмите «Открыть файл мода».")
            self.ring_hint.setText("Откройте мод, чтобы увидеть прогресс.")
        self.continue_btn.setVisible(bool(project))

        has = bool(project)
        started = s["translated"] > 0
        self.steps[0].set_state("done" if has else "current")
        self.steps[1].set_state("todo" if not has else ("done" if s["percent"] >= 100 else "current"))
        self.steps[2].set_state("current" if (has and started) else "todo")

    # ------------------------------------------------------------------
    def _open_mod(self):
        if self._busy:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Открыть файл мода", "",
            "Файлы модов BG3 (*.pak *.zip *.xml);;Все файлы (*)"
        )
        if path:
            self._start_import(path, False)

    def _open_folder(self):
        if self._busy:
            return
        path = QFileDialog.getExistingDirectory(self, "Открыть распакованную папку мода")
        if path:
            self._start_import(path, True)

    def _set_busy(self, busy: bool):
        self._busy = busy
        self.open_btn.setEnabled(not busy)
        self.open_folder_btn.setEnabled(not busy)
        self.busy_bar.setVisible(busy)

    def _start_import(self, path: str, is_folder: bool):
        if self._busy:
            return
        from .editor import ImportWorker

        self.main.toast("Читаю мод…", "info")
        self._set_busy(True)

        self._thread = QThread()
        self._worker = ImportWorker(path, is_folder,
                                    self.source_lang.currentData(),
                                    self.target_lang.currentData())
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_import_done)
        self._worker.failed.connect(self._on_import_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.start()

    def _on_import_done(self, project):
        self.state.project = project
        self.state.project_changed.emit()
        self.main.toast(f"Загружено строк: {project.total_entries}", "success")
        self._set_busy(False)
        self.main.navigate("editor")

    def _on_import_failed(self, error: str):
        self.main.toast(f"Не удалось импортировать: {error}", "error", 6000)
        self._set_busy(False)
