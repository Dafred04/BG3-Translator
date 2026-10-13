# BG3 Mod Translator v2

Современное desktop-приложение для локализации модов Baldur's Gate 3.
Полностью переработанная версия с сохранением функционала оригинала.

## Возможности

- **Импорт модов**: `.pak` (LSPK v17/v18, LZ4/Zlib/Zstd), `.zip`, `.xml`/`.loc`, распакованные папки
- **Редактор переводов**: таблица source→translation, поиск, фильтры (все/непереведённые/переведённые/ошибки), правка двойным кликом
- **Автоперевод**: Google Translate (бесплатно, без ключа) + OpenAI-совместимые API (OpenAI, DeepSeek, OpenRouter и др.)
- **Словарь (translation memory)**: SQLite, автоматическое повторное использование переводов между модами; сначала словарь, потом провайдер
- **Валидация плейсхолдеров**: `<LSTag>`, `&entity;`, `{0}`, `[1]` — повреждённые переводы отклоняются (strict mode)
- **Защита версий**: версия экспортируемой локализации никогда не ниже исходной
- **Экспорт**: `.xml` (локализация) и `.pak` (готовый BG3-пакет с внутренним путём `Public/<Mod>/Localization/`)
- **Настройки**: тема (light/dark/system), провайдер, API-ключ, модель, таймаут, строгий режим
- **UX**: toast-уведомления, прогресс батч-перевода, фоновый импорт без блокировки UI

## Запуск

```bash
pip install -r requirements.txt
python main.py
```

## Тесты

```bash
python tests\test_core.py       # валидация плейсхолдеров + XML round-trip
python tests\test_services.py   # словарь + движок перевода (offline)
python tests\test_pak.py        # pak round-trip + ImportWorker (pak/zip)
python tests\test_ui.py         # UI smoke test (offscreen)
```

## Структура

```
main.py                     — точка входа
src/bg3_translator/
  config.py                 — пути, настройки, языки
  models/translation.py     — TranslationEntry, DictionaryEntry, ModMetadata, TranslationProject
  core/
    locaxml.py              — парсинг/генерация BG3 XML локализации
    validation.py           — извлечение/сравнение плейсхолдеров
    pak.py                  — чтение/запись LSPK v17/v18
  services/
    dictionary.py           — SQLite translation memory
    providers.py            — Google Free, OpenAI-compatible
    engine.py               — словарь → провайдер → валидация
  ui/
    theme.py                — дизайн-система (токены + QSS light/dark)
    widgets.py              — Card, StatTile, PrimaryButton, Toast
    main_window.py          — окно с sidebar-навигацией
    state.py                — общее состояние (AppState)
    pages/                  — dashboard, editor, dictionary, settings
tests/                      — smoke-тесты всех слоёв
Docs/PROGRESS.md            — журнал разработки
```

## Примечания

- `.pak`-формат реализован по спецификации LSLib (Norbyte); BG3 — товарный знак Larian Studios. Приложение не связано с Larian.
- Google Free использует неофициальный endpoint translate.googleapis.com; для продакшн-переводов рекомендуется настроить OpenAI-совместимый API-ключ в Settings.