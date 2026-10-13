"""Settings page: translation providers, theme, validation options."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from ..state import get_app_state
from ..widgets import Card, PrimaryButton
from ...config import save_settings, TranslationProviderConfig, get_settings


class SettingsPage(QWidget):
    """App settings: provider keys, theme, validation."""

    def __init__(self, main_window):
        super().__init__()
        self.main = main_window
        self.state = get_app_state()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 28, 32, 28)
        lay.setSpacing(16)

        header = QLabel("Настройки")
        header.setObjectName("Title")
        lay.addWidget(header)

        scroll_host = QWidget()
        host_lay = QVBoxLayout(scroll_host)
        host_lay.setContentsMargins(0, 0, 8, 0)
        host_lay.setSpacing(16)

        # --- Appearance ---
        theme_card = Card()
        tc_lay = QFormLayout(theme_card)
        tc_lay.setContentsMargins(24, 20, 24, 20)
        tc_lay.setHorizontalSpacing(20)
        tc_lay.setVerticalSpacing(12)
        tc_title = QLabel("Оформление")
        tc_title.setObjectName("Title")
        tc_lay.addRow(tc_title)
        self.theme_box = QComboBox()
        self.theme_box.addItem("Светлая", "light")
        self.theme_box.addItem("Тёмная", "dark")
        self.theme_box.addItem("Как в системе", "system")
        tc_lay.addRow("Тема", self.theme_box)
        host_lay.addWidget(theme_card)

        # --- Translation provider ---
        prov_card = Card()
        pc_lay = QFormLayout(prov_card)
        pc_lay.setContentsMargins(24, 20, 24, 20)
        pc_lay.setHorizontalSpacing(20)
        pc_lay.setVerticalSpacing(12)
        pc_title = QLabel("Провайдер перевода")
        pc_title.setObjectName("Title")
        pc_lay.addRow(pc_title)

        self.provider_box = QComboBox()
        self.provider_box.addItem("Google Переводчик (бесплатно)", "google_free")
        self.provider_box.addItem("OpenAI-совместимый (Gemini / DeepSeek / OpenAI)", "openai_compatible")
        pc_lay.addRow("Провайдер", self.provider_box)

        self.api_key = QLineEdit()
        self.api_key.setPlaceholderText("Ключ API (для провайдеров с ключом)")
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        pc_lay.addRow("Ключ API", self.api_key)

        self.model = QLineEdit()
        self.model.setPlaceholderText("напр. gemini-2.0-flash, gpt-4o-mini, deepseek-chat")
        pc_lay.addRow("Модель", self.model)

        self.base_url = QLineEdit()
        self.base_url.setPlaceholderText("Базовый URL (необязательно, для совместимых API)")
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
        vc_lay.addWidget(v_title)
        self.check_placeholders = QCheckBox("Проверять плейсхолдеры (LSTag, {0}, &entity;)")
        self.check_strict = QCheckBox("Строгий режим — отклонять перевод с ошибками плейсхолдеров")
        vc_lay.addWidget(self.check_placeholders)
        vc_lay.addWidget(self.check_strict)
        host_lay.addWidget(val_card)

        host_lay.addStretch(1)

        from PySide6.QtWidgets import QScrollArea
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(scroll_host)
        lay.addWidget(scroll, 1)

        # Save button
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        save_btn = PrimaryButton("Сохранить настройки")
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)
        lay.addLayout(btn_row)

        self._load()

    def _load(self):
        s = get_settings()
        idx = self.theme_box.findData(s.theme)
        self.theme_box.setCurrentIndex(max(0, idx))
        idx = self.provider_box.findData(s.default_provider)
        self.provider_box.setCurrentIndex(max(0, idx))
        prov = s.providers.get(s.default_provider)
        if prov:
            self.api_key.setText(prov.api_key)
            self.model.setText(prov.model)
            self.base_url.setText(prov.base_url)
        self.timeout.setValue(s.timeout)
        self.check_placeholders.setChecked(s.validate_placeholders)
        self.check_strict.setChecked(s.strict_mode)

    def _save(self):
        s = get_settings()
        s.theme = self.theme_box.currentData()
        s.default_provider = self.provider_box.currentData()
        prov = s.providers.get(s.default_provider) or TranslationProviderConfig(name=s.default_provider)
        prov.api_key = self.api_key.text().strip()
        prov.model = self.model.text().strip()
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