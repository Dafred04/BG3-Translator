"""Settings page: провайдеры перевода, тема, проверка плейсхолдеров."""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from ..state import get_app_state
from ..widgets import Card, GhostButton, PrimaryButton
from ...config import save_settings, TranslationProviderConfig, get_settings

_HINTS = {
    "gemini": "Gemini — модель ИИ для автоматического перевода текста модов. "
              "Ключ можно бесплатно получить в Google AI Studio.",
    "openai_compatible": "Подойдёт любой сервис с OpenAI-совместимым API: OpenAI, DeepSeek, "
                         "OpenRouter и т.д. Укажите ключ, модель и базовый URL.",
    "google_free": "Бесплатный веб-переводчик: ключ не нужен, но качество и стабильность ниже.",
}


class SettingsPage(QWidget):
    """App settings: provider keys, theme, validation."""

    def __init__(self, main_window):
        super().__init__()
        self.main = main_window
        self.state = get_app_state()
        self._loading = True
        self._current_provider = ""
        self._drafts: dict[str, tuple[str, str, str]] = {}

        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 28, 32, 28)
        lay.setSpacing(16)

        header = QLabel("Настройки")
        header.setObjectName("PageTitle")
        lay.addWidget(header)

        scroll_host = QWidget()
        host_lay = QVBoxLayout(scroll_host)
        host_lay.setContentsMargins(0, 0, 10, 0)
        host_lay.setSpacing(16)

        # --- Appearance ---
        theme_card, tc_lay = self._form_card("Оформление",
                                             "Тема применяется сразу — можно сравнить, не сохраняя.")
        self.theme_box = QComboBox()
        self.theme_box.addItem("Светлая", "light")
        self.theme_box.addItem("Тёмная", "dark")
        self.theme_box.addItem("Как в системе", "system")
        self.theme_box.currentIndexChanged.connect(self._preview_theme)
        tc_lay.addRow("Тема", self.theme_box)
        host_lay.addWidget(theme_card)

        # --- Translation provider ---
        prov_card, pc_lay = self._form_card("Провайдер перевода",
                                            "Кто будет переводить строки, которых нет в словаре.")
        self.provider_box = QComboBox()
        self.provider_box.addItem("Google Gemini (рекомендуется)", "gemini")
        self.provider_box.addItem("OpenAI-совместимый (DeepSeek / OpenAI)", "openai_compatible")
        self.provider_box.addItem("Google Переводчик (бесплатно, нестабильно)", "google_free")
        self.provider_box.currentIndexChanged.connect(self._on_provider_changed)
        pc_lay.addRow("Провайдер", self.provider_box)

        self.hint = QLabel(_HINTS["gemini"])
        self.hint.setObjectName("Subtitle")
        self.hint.setWordWrap(True)
        pc_lay.addRow("", self.hint)

        self.api_key = QLineEdit()
        self.api_key.setPlaceholderText("Ключ API Gemini (обязателен)")
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        key_row = QHBoxLayout()
        key_row.setSpacing(8)
        key_row.addWidget(self.api_key, 1)
        self.eye_btn = GhostButton("Показать")
        self.eye_btn.setCheckable(True)
        self.eye_btn.toggled.connect(self._toggle_key_visible)
        key_row.addWidget(self.eye_btn)
        key_box = QWidget()
        key_box.setLayout(key_row)
        key_row.setContentsMargins(0, 0, 0, 0)
        pc_lay.addRow("Ключ API", key_box)

        # Model: dropdown, populated from the API, but still editable
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.lineEdit().setPlaceholderText("напр. gemini-2.5-flash")
        model_row = QHBoxLayout()
        model_row.setContentsMargins(0, 0, 0, 0)
        model_row.setSpacing(8)
        model_row.addWidget(self.model, 1)
        self.fetch_models_btn = GhostButton("Загрузить модели")
        self.fetch_models_btn.setToolTip("Запросить список моделей через API")
        self.fetch_models_btn.clicked.connect(self._fetch_models)
        model_row.addWidget(self.fetch_models_btn)
        model_box = QWidget()
        model_box.setLayout(model_row)
        pc_lay.addRow("Модель", model_box)

        self.base_url = QLineEdit()
        self.base_url.setPlaceholderText("Базовый URL (пусто = по умолчанию для провайдера)")
        pc_lay.addRow("Базовый URL", self.base_url)

        self.timeout = QSpinBox()
        self.timeout.setRange(10, 300)
        self.timeout.setSuffix(" с")
        pc_lay.addRow("Тайм-аут", self.timeout)
        host_lay.addWidget(prov_card)

        # --- Validation ---
        val_card = Card()
        vc_lay = QVBoxLayout(val_card)
        vc_lay.setContentsMargins(24, 20, 24, 20)
        vc_lay.setSpacing(10)
        v_title = QLabel("Проверка")
        v_title.setObjectName("Title")
        v_hint = QLabel("Защищает игровые теги от порчи: ИИ иногда «переводит» то, что трогать нельзя.")
        v_hint.setObjectName("Subtitle")
        v_hint.setWordWrap(True)
        vc_lay.addWidget(v_title)
        vc_lay.addWidget(v_hint)
        self.check_placeholders = QCheckBox("Проверять плейсхолдеры (LSTag, {0}, &entity;)")
        self.check_strict = QCheckBox("Строгий режим — отклонять перевод с ошибками плейсхолдеров")
        vc_lay.addWidget(self.check_placeholders)
        vc_lay.addWidget(self.check_strict)
        host_lay.addWidget(val_card)
        host_lay.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(scroll_host)
        lay.addWidget(scroll, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.save_btn = PrimaryButton("Сохранить настройки")
        self.save_btn.clicked.connect(self._save)
        btn_row.addWidget(self.save_btn)
        lay.addLayout(btn_row)

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
        self.theme_box.setCurrentIndex(max(0, self.theme_box.findData(s.theme)))
        self.provider_box.setCurrentIndex(max(0, self.provider_box.findData(s.default_provider)))
        self._current_provider = self.provider_box.currentData()
        self._fill_provider_fields(self._current_provider)
        self.timeout.setValue(s.timeout)
        self.check_placeholders.setChecked(s.validate_placeholders)
        self.check_strict.setChecked(s.strict_mode)
        self._update_provider_ui()
        self._loading = False

    def _fill_provider_fields(self, name: str):
        if name in self._drafts:
            key, model, url = self._drafts[name]
        else:
            prov = get_settings().providers.get(name)
            key, model, url = (prov.api_key, prov.model, prov.base_url) if prov else ("", "", "")
        self.api_key.setText(key)
        self.model.setCurrentText(model)
        self.base_url.setText(url)

    def _update_provider_ui(self):
        name = self.provider_box.currentData()
        self.hint.setText(_HINTS.get(name, ""))
        if name == "gemini":
            self.api_key.setPlaceholderText("Ключ API Gemini (обязателен)")
        elif name == "openai_compatible":
            self.api_key.setPlaceholderText("Ключ API (OpenAI / DeepSeek…)")
        else:
            self.api_key.setPlaceholderText("Ключ не требуется")
        self.api_key.setEnabled(name != "google_free")
        self.fetch_models_btn.setEnabled(name == "gemini")

    def _on_provider_changed(self):
        """При смене провайдера подставляем его сохранённые поля (черновик не теряем)."""
        if self._loading:
            return
        self._drafts[self._current_provider] = (
            self.api_key.text(), self.model.currentText(), self.base_url.text())
        self._current_provider = self.provider_box.currentData()
        self._fill_provider_fields(self._current_provider)
        self._update_provider_ui()

    def _toggle_key_visible(self, shown: bool):
        self.api_key.setEchoMode(QLineEdit.EchoMode.Normal if shown else QLineEdit.EchoMode.Password)
        self.eye_btn.setText("Скрыть" if shown else "Показать")

    def _preview_theme(self):
        if not self._loading:
            self.main._apply_theme(self.theme_box.currentData())

    def _fetch_models(self):
        """Query the provider API for available models and populate the dropdown."""
        from ...services.providers import get_provider, TranslationError
        name = self.provider_box.currentData()
        api_key = self.api_key.text().strip()
        base_url = self.base_url.text().strip()
        self.fetch_models_btn.setEnabled(False)
        self.fetch_models_btn.setText("Загружаю…")
        try:
            provider = get_provider(name, api_key=api_key, base_url=base_url,
                                    timeout=self.timeout.value())
            models = provider.list_models()
        except TranslationError as exc:
            self.main.toast(f"Не удалось получить список моделей: {exc}", "error", 6000)
            return
        except Exception as exc:
            self.main.toast(f"Ошибка запроса моделей: {exc}", "error", 6000)
            return
        finally:
            self.fetch_models_btn.setText("Загрузить модели")
            self._update_provider_ui()
        if not models:
            self.main.toast("Модели не найдены. Проверьте ключ API.", "warning")
            return
        current = self.model.currentText().strip()
        self.model.clear()
        self.model.addItems(models)
        if current in models:
            self.model.setCurrentText(current)
        self.main.toast(f"Загружено моделей: {len(models)}", "success")

    def _save(self):
        s = get_settings()
        s.theme = self.theme_box.currentData()
        s.default_provider = self.provider_box.currentData()
        prov = s.providers.get(s.default_provider) or TranslationProviderConfig(name=s.default_provider)
        prov.api_key = self.api_key.text().strip()
        prov.model = self.model.currentText().strip()
        prov.base_url = self.base_url.text().strip()
        s.providers[s.default_provider] = prov
        s.timeout = self.timeout.value()
        s.validate_placeholders = self.check_placeholders.isChecked()
        s.strict_mode = self.check_strict.isChecked()
        save_settings(s)
        self.state.settings = s
        self.state.reset_engine()
        self.main._apply_theme(s.theme)
        self.main.toast("Настройки сохранены", "success")
        self.save_btn.setText("✔  Сохранено")
        QTimer.singleShot(1600, lambda: self.save_btn.setText("Сохранить настройки"))
