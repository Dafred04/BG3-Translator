"""Настройки: провайдер, параметры перевода, проверка, автосохранение, оформление."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
    QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from ..state import api_key_for, get_app_state
from ..widgets import Card, GhostButton, PrimaryButton
from ...config import PATHS, TranslationProviderConfig, get_settings, save_settings
from ...services import keystore

log = logging.getLogger(__name__)

_HINTS = {
    "gemini": "Gemini — модель ИИ для автоматического перевода текста модов. "
              "Ключ можно бесплатно получить в Google AI Studio.",
    "openai_compatible": "Любой сервис с OpenAI-совместимым API: OpenAI, DeepSeek, OpenRouter. "
                         "Локальные Ollama / LM Studio работают без ключа — укажите только базовый URL.",
    "google_free": "Бесплатный веб-переводчик: ключ не нужен, но качество и стабильность ниже.",
}


class _Task(QObject):
    """Выполняет функцию в фоне. Нужен, чтобы сетевые проверки не замораживали окно."""

    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self._fn = fn

    def run(self):
        try:
            self.done.emit(self._fn())
        except Exception as exc:
            self.failed.emit(str(exc) or exc.__class__.__name__)


class SettingsPage(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main = main_window
        self.state = get_app_state()
        self._loading = True
        self._current_provider = ""
        self._drafts: dict[str, tuple[str, str, str]] = {}
        self._jobs: list = []                       # (thread, task): держим ссылки до завершения

        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 28, 32, 28)
        lay.setSpacing(16)
        header = QLabel("Настройки")
        header.setObjectName("PageTitle")
        lay.addWidget(header)

        host = QWidget()
        hl = QVBoxLayout(host)
        hl.setContentsMargins(0, 0, 10, 0)
        hl.setSpacing(16)

        # --- Оформление ---
        card, f = self._form_card("Оформление", "Тема применяется сразу — можно сравнить, не сохраняя.")
        self.theme_box = QComboBox()
        self.theme_box.addItem("Светлая", "light")
        self.theme_box.addItem("Тёмная", "dark")
        self.theme_box.addItem("Как в системе", "system")
        self.theme_box.currentIndexChanged.connect(self._preview_theme)
        f.addRow("Тема", self.theme_box)
        hl.addWidget(card)

        # --- Провайдер ---
        card, f = self._form_card("Провайдер перевода",
                                  "Кто переводит строки, которых нет в словаре.")
        self.provider_box = QComboBox()
        self.provider_box.addItem("Google Gemini (рекомендуется)", "gemini")
        self.provider_box.addItem("OpenAI-совместимый (DeepSeek / OpenAI / Ollama)", "openai_compatible")
        self.provider_box.addItem("Google Переводчик (бесплатно, нестабильно)", "google_free")
        self.provider_box.currentIndexChanged.connect(self._on_provider_changed)
        f.addRow("Провайдер", self.provider_box)
        self.hint = QLabel(_HINTS["gemini"])
        self.hint.setObjectName("Subtitle")
        self.hint.setWordWrap(True)
        f.addRow("", self.hint)

        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        key_row = QHBoxLayout()
        key_row.setContentsMargins(0, 0, 0, 0)
        key_row.setSpacing(8)
        key_row.addWidget(self.api_key, 1)
        self.eye_btn = GhostButton("Показать")
        self.eye_btn.setCheckable(True)
        self.eye_btn.toggled.connect(self._toggle_key_visible)
        key_row.addWidget(self.eye_btn)
        key_box = QWidget()
        key_box.setLayout(key_row)
        f.addRow("Ключ API", key_box)
        self.key_note = QLabel("")
        self.key_note.setObjectName("Hint")
        self.key_note.setWordWrap(True)
        f.addRow("", self.key_note)

        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.lineEdit().setPlaceholderText("напр. gemini-2.5-flash")
        model_row = QHBoxLayout()
        model_row.setContentsMargins(0, 0, 0, 0)
        model_row.setSpacing(8)
        model_row.addWidget(self.model, 1)
        self.fetch_models_btn = GhostButton("Загрузить модели")
        self.fetch_models_btn.clicked.connect(self._fetch_models)
        model_row.addWidget(self.fetch_models_btn)
        model_box = QWidget()
        model_box.setLayout(model_row)
        f.addRow("Модель", model_box)

        self.base_url = QLineEdit()
        self.base_url.setPlaceholderText("Базовый URL (пусто = по умолчанию для провайдера)")
        f.addRow("Базовый URL", self.base_url)

        self.timeout = QSpinBox()
        self.timeout.setRange(10, 300)
        self.timeout.setSuffix(" с")
        f.addRow("Тайм-аут", self.timeout)

        test_row = QHBoxLayout()
        test_row.setContentsMargins(0, 0, 0, 0)
        self.test_btn = GhostButton("Проверить подключение")
        self.test_btn.clicked.connect(self._test_connection)
        self.test_result = QLabel("")
        self.test_result.setWordWrap(True)
        test_row.addWidget(self.test_btn)
        test_row.addWidget(self.test_result, 1)
        tb = QWidget()
        tb.setLayout(test_row)
        f.addRow("", tb)
        hl.addWidget(card)

        # --- Параметры перевода ---
        card, f = self._form_card("Как переводить",
                                  "Скорость, надёжность и стиль. Значения по умолчанию подходят большинству модов.")
        self.batch = QSpinBox()
        self.batch.setRange(1, 100)
        self.batch.setToolTip("Сколько строк уходит в одном запросе")
        f.addRow("Строк в запросе", self.batch)
        self.parallel = QSpinBox()
        self.parallel.setRange(1, 8)
        self.parallel.setToolTip("Бесплатные тарифы часто ограничивают частоту запросов — при ошибках 429 уменьшите")
        f.addRow("Параллельных запросов", self.parallel)
        self.retries = QSpinBox()
        self.retries.setRange(0, 8)
        f.addRow("Повторов при сбое", self.retries)
        self.shield = QCheckBox("Защищать теги и плейсхолдеры (рекомендуется)")
        self.shield.setToolTip("Теги заменяются метками перед отправкой ИИ и возвращаются после — так их не испортить")
        f.addRow("", self.shield)
        self.use_dict = QCheckBox("Сначала искать в словаре")
        f.addRow("", self.use_dict)
        self.use_glossary = QCheckBox("Передавать ИИ термины из глоссария")
        f.addRow("", self.use_glossary)
        self.use_fuzzy = QCheckBox("Подставлять похожие строки из словаря")
        f.addRow("", self.use_fuzzy)
        self.fuzzy = QSpinBox()
        self.fuzzy.setRange(60, 99)
        self.fuzzy.setSuffix(" %")
        self.fuzzy.setToolTip("Минимальная похожесть. Такие строки получают статус «На проверке».")
        f.addRow("Порог похожести", self.fuzzy)
        self.use_fuzzy.toggled.connect(self.fuzzy.setEnabled)
        self.style = QLineEdit()
        self.style.setPlaceholderText("напр.: живой литературный язык, обращение на «вы»")
        f.addRow("Стиль", self.style)
        self.prompt = QPlainTextEdit()
        self.prompt.setPlaceholderText("Дополнительные инструкции для ИИ (необязательно)")
        self.prompt.setFixedHeight(80)
        f.addRow("Свои инструкции", self.prompt)
        hl.addWidget(card)

        # --- Проверка ---
        card, f = self._form_card("Проверка",
                                  "Защищает игровые теги от порчи: ИИ иногда «переводит» то, что трогать нельзя.")
        self.check_placeholders = QCheckBox("Проверять плейсхолдеры (LSTag, {0}, &entity;, <br>)")
        self.check_strict = QCheckBox("Строки с ошибками помечать «На проверке»")
        self.check_strict.setToolTip("Перевод сохраняется, но строка попадёт в фильтр «На проверке»")
        f.addRow("", self.check_placeholders)
        f.addRow("", self.check_strict)
        hl.addWidget(card)

        # --- Сохранение и журнал ---
        card, f = self._form_card("Сохранение", "Проект сохраняется сам, чтобы работа не пропала.")
        self.autosave = QCheckBox("Автосохранение проекта")
        f.addRow("", self.autosave)
        self.autosave_sec = QSpinBox()
        self.autosave_sec.setRange(5, 600)
        self.autosave_sec.setSuffix(" с")
        f.addRow("Не чаще, чем раз в", self.autosave_sec)
        self.autosave.toggled.connect(self.autosave_sec.setEnabled)
        logs = GhostButton("Открыть папку журналов")
        logs.setToolTip("Если что-то пошло не так, приложите файл из этой папки к сообщению об ошибке")
        logs.clicked.connect(self._open_logs)
        f.addRow("", logs)
        hl.addWidget(card)
        hl.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(host)
        lay.addWidget(scroll, 1)

        row = QHBoxLayout()
        row.addStretch(1)
        self.save_btn = PrimaryButton("Сохранить настройки")
        self.save_btn.clicked.connect(self._save)
        row.addWidget(self.save_btn)
        lay.addLayout(row)

        self._load()

    # ------------------------------------------------------------------
    @staticmethod
    def _form_card(title: str, subtitle: str):
        card = Card()
        form = QFormLayout(card)
        form.setContentsMargins(24, 20, 24, 20)
        form.setHorizontalSpacing(20)
        form.setVerticalSpacing(12)
        t = QLabel(title)
        t.setObjectName("Title")
        s = QLabel(subtitle)
        s.setObjectName("Subtitle")
        s.setWordWrap(True)
        form.addRow(t)
        form.addRow(s)
        return card, form

    def _load(self):
        self._loading = True
        s = get_settings()
        g = lambda name, default: getattr(s, name, default)               # noqa: E731
        self.theme_box.setCurrentIndex(max(0, self.theme_box.findData(s.theme)))
        self.provider_box.setCurrentIndex(max(0, self.provider_box.findData(s.default_provider)))
        self._current_provider = self.provider_box.currentData()
        self._fill_provider_fields(self._current_provider)
        self.timeout.setValue(int(s.timeout))
        self.batch.setValue(int(g("batch_size", 25)))
        self.parallel.setValue(int(g("max_concurrent_requests", 3)))
        self.retries.setValue(int(g("retry_attempts", 3)))
        self.shield.setChecked(bool(g("shield_placeholders", True)))
        self.use_dict.setChecked(bool(g("use_dictionary", True)))
        self.use_glossary.setChecked(bool(g("use_glossary", True)))
        self.use_fuzzy.setChecked(bool(g("use_fuzzy", False)))
        self.fuzzy.setValue(int(round(float(g("dictionary_match_threshold", 0.85)) * 100)))
        self.fuzzy.setEnabled(self.use_fuzzy.isChecked())
        self.style.setText(str(g("translation_style", "")))
        self.prompt.setPlainText(str(g("custom_prompt", "")))
        self.check_placeholders.setChecked(bool(g("validate_placeholders", True)))
        self.check_strict.setChecked(bool(g("strict_mode", False)))
        self.autosave.setChecked(bool(g("auto_save", True)))
        self.autosave_sec.setValue(int(g("auto_save_interval", 30)))
        self.autosave_sec.setEnabled(self.autosave.isChecked())
        self._update_provider_ui()
        self._loading = False

    def _fill_provider_fields(self, name: str):
        if name in self._drafts:
            key, model, url = self._drafts[name]
        else:
            s = get_settings()
            prov = s.providers.get(name)
            key = api_key_for(s, name)
            model, url = (prov.model, prov.base_url) if prov else ("", "")
        self.api_key.setText(key)
        self.model.setCurrentText(model)
        self.base_url.setText(url)

    def _update_provider_ui(self):
        name = self.provider_box.currentData()
        self.hint.setText(_HINTS.get(name, ""))
        self.api_key.setPlaceholderText({
            "gemini": "Ключ API Gemini (обязателен)",
            "openai_compatible": "Ключ API (можно пусто для локальных серверов)",
        }.get(name, "Ключ не требуется"))
        self.api_key.setEnabled(name != "google_free")
        self.fetch_models_btn.setEnabled(name in ("gemini", "openai_compatible"))
        self.model.lineEdit().setPlaceholderText(
            {"gemini": "напр. gemini-2.5-flash", "openai_compatible": "напр. deepseek-chat"}.get(name, ""))
        self.base_url.setEnabled(name != "google_free")
        if name == "google_free":
            self.key_note.setText("")
        elif keystore.available():
            self.key_note.setText("🔒 Ключ хранится в защищённом хранилище системы, а не в файле настроек.")
        else:
            self.key_note.setText("Ключ хранится в файле настроек. Установите пакет keyring — "
                                  "тогда он будет лежать в защищённом хранилище.")

    def _on_provider_changed(self):
        if self._loading:
            return
        self._drafts[self._current_provider] = (
            self.api_key.text(), self.model.currentText(), self.base_url.text())
        self._current_provider = self.provider_box.currentData()
        self._fill_provider_fields(self._current_provider)
        self._update_provider_ui()
        self.test_result.setText("")

    def _toggle_key_visible(self, shown: bool):
        self.api_key.setEchoMode(QLineEdit.EchoMode.Normal if shown else QLineEdit.EchoMode.Password)
        self.eye_btn.setText("Скрыть" if shown else "Показать")

    def _preview_theme(self):
        if not self._loading:
            self.main._apply_theme(self.theme_box.currentData())

    def _open_logs(self):
        d = Path(PATHS.cache_dir) / "logs"
        d.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(d)))

    # ------------------------------------------------------------------
    # Сеть: в фоне
    # ------------------------------------------------------------------
    def _provider_from_form(self):
        from ...services.providers import get_provider
        p = get_provider(self.provider_box.currentData(), api_key=self.api_key.text().strip(),
                         model=self.model.currentText().strip(), base_url=self.base_url.text().strip(),
                         timeout=self.timeout.value())
        p.max_retries = 0                                    # при проверке повторы только раздражают
        return p

    def _run_bg(self, fn, on_done, on_fail):
        thread = QThread(self)
        task = _Task(fn)
        task.moveToThread(thread)
        thread.started.connect(task.run)
        task.done.connect(on_done)
        task.failed.connect(on_fail)
        for sig in (task.done, task.failed):
            sig.connect(thread.quit)
        job = (thread, task)
        self._jobs.append(job)
        thread.finished.connect(lambda j=job: self._jobs.remove(j) if j in self._jobs else None)
        thread.start()

    def _test_connection(self):
        try:
            provider = self._provider_from_form()
        except Exception as exc:
            self._set_test(f"✖ {exc}", ok=False)
            return
        self.test_btn.setEnabled(False)
        self.test_btn.setText("Проверяю…")
        self.test_result.setText("")

        def done(res):
            sec, text = res
            self._end_test()
            self._set_test(f"✔ Работает: {sec:.1f} с, ответ «{text}»", ok=True)

        def fail(msg):
            self._end_test()
            self._set_test(f"✖ {msg}", ok=False)

        self._run_bg(provider.test_connection, done, fail)

    def _end_test(self):
        self.test_btn.setEnabled(True)
        self.test_btn.setText("Проверить подключение")

    def _set_test(self, text: str, ok: bool):
        self.test_result.setObjectName("Subtitle" if ok else "IssueError")
        self.test_result.style().unpolish(self.test_result)
        self.test_result.style().polish(self.test_result)
        self.test_result.setText(text)

    def _fetch_models(self):
        try:
            provider = self._provider_from_form()
        except Exception as exc:
            self.main.toast(f"Не удалось создать провайдера: {exc}", "error", 6000)
            return
        self.fetch_models_btn.setEnabled(False)
        self.fetch_models_btn.setText("Загружаю…")

        def done(models):
            self.fetch_models_btn.setText("Загрузить модели")
            self._update_provider_ui()
            if not models:
                self.main.toast("Модели не найдены. Проверьте ключ API и адрес.", "warning")
                return
            current = self.model.currentText().strip()
            self.model.clear()
            self.model.addItems(models)
            self.model.setCurrentText(current if current in models else models[0])
            self.main.toast(f"Загружено моделей: {len(models)}", "success")

        def fail(msg):
            self.fetch_models_btn.setText("Загрузить модели")
            self._update_provider_ui()
            self.main.toast(f"Не удалось получить список моделей: {msg}", "error", 6000)

        self._run_bg(provider.list_models, done, fail)

    # ------------------------------------------------------------------
    def _save(self):
        s = get_settings()
        name = self.provider_box.currentData()
        s.theme = self.theme_box.currentData()
        s.default_provider = name

        prov = s.providers.get(name) or TranslationProviderConfig(name=name)
        key = self.api_key.text().strip()
        if name != "google_free":
            stored = keystore.set_api_key(name, key)
            prov.api_key = "" if stored else key              # в файле ключ остаётся только как запасной вариант
        prov.model = self.model.currentText().strip()
        prov.base_url = self.base_url.text().strip()
        s.providers[name] = prov

        s.timeout = self.timeout.value()
        s.batch_size = self.batch.value()
        s.max_concurrent_requests = self.parallel.value()
        s.retry_attempts = self.retries.value()
        s.shield_placeholders = self.shield.isChecked()
        s.use_dictionary = self.use_dict.isChecked()
        s.use_glossary = self.use_glossary.isChecked()
        s.use_fuzzy = self.use_fuzzy.isChecked()
        s.dictionary_match_threshold = self.fuzzy.value() / 100.0
        s.translation_style = self.style.text().strip()
        s.custom_prompt = self.prompt.toPlainText().strip()
        s.validate_placeholders = self.check_placeholders.isChecked()
        s.strict_mode = self.check_strict.isChecked()
        s.auto_save = self.autosave.isChecked()
        s.auto_save_interval = self.autosave_sec.value()

        save_settings(s)
        self.state.settings = s
        self._drafts.clear()
        if self.state.engine.is_running():
            self.main.toast("Настройки сохранены. Для идущего перевода они вступят в силу в следующий раз.",
                            "info", 5000)
        else:
            self.state.reset_engine()
            self.main.toast("Настройки сохранены", "success")
        self.main._apply_theme(s.theme)
        self.main._refresh_provider_chip()
        self.save_btn.setText("✔  Сохранено")
        QTimer.singleShot(1600, lambda: self.save_btn.setText("Сохранить настройки"))
