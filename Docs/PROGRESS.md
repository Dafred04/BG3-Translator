# BG3 Mod Translator v2 — прогресс

Полная переработка PySide6-приложения "BG3 Mod Translator" (перевод модов Baldur's Gate 3).
Проект: `C:\Users\user\Desktop\BG3_ModTranslator_New`

## Функционал старой версии (сохранить всё)
- Загрузка модов: .pak / .zip / распакованная папка
- Извлечение локализации (XML/LOCA) из pak (LSPK v18, LZ4/Zstd)
- Редактор переводов side-by-side, поиск/фильтры
- Автоперевод: AI (OpenAI-совместимые) + Google Free
- Словарь/переводческая память (reuse переводов)
- Валидация плейсхолдеров: `<LSTag/>`, `&entity;`, `{0}`, `[1]`, `\n`
- Версионная защита loca (target version >= source)
- Экспорт: .pak / .xml / .zip (BG3MM-совместимый)
- Настройки: провайдеры, API-ключи, пакетный размер, строгий режим

## Архитектура
```
src/bg3_translator/
  config.py              — пути, настройки, языки
  models/translation.py  — TranslationEntry, DictionaryEntry, ModMetadata, TranslationProject
  core/                  — pak.py, loca.py, locaxml.py, mods.py, validation.py
  services/              — providers.py, dictionary.py, engine.py (async)
  ui/                    — PySide6: theme, widgets, main_window, pages/
  utils/                 — helpers
```

## Milestones
- [x] M1: Аудит старой версии, проектирование архитектуры
- [x] M2: config.py + models (round-trip сериализация)
- [x] M3: core — XML локализации (locaxml.py), валидация плейсхолдеров (validation.py)
- [x] M4: services — словарь (SQLite), провайдеры перевода (Google Free + OpenAI-совместимые)
- [x] M5: UI — дизайн-система, главное окно, страницы Dashboard/Editor/Dictionary/Settings
- [x] M6: core/pak.py — чтение/запись LSPK v17/v18, импорт/экспорт
- [x] M7: Финальное тестирование запуска, requirements.txt, README.md
- [x] M8: bugfix unique_tav.pak — корректный v18 file list + бинарный .loca + flat XML + регресс-тест
- [x] M9: .gitignore для тестовых модов и скриптов анализа
- [x] M10: восстановление ядра после компактификации контекста
- [x] M11: async-перевод в UI — фикс зависания на «Перевести всё», статус-бар, кнопка «Остановить»
- [x] M12: полная русификация интерфейса (весь UI на русском, дефолт en→ru)

## M10 — восстановление ядра (post-compaction repair)
Файлы были повреждены при компактификации контекста. Исправлено:
- services/engine.py — полностью переписан. Было: тройное дублирование классов
  StageId/JobProgress/TranslationEngine, метод _run_core внутри датакласса, отсутствовал
  _emit, использовалось несуществующее поле done.
  Стало: чистый async-движок (worker-thread + PySide6 signals, UI не блокируется),
  подробный прогресс (этап, текущий мод/файл, счётчики, скорость, ETA, ошибки),
  + синхронный API translate_entry / translate_batch для тестов и точечного перевода.
- models/translation.py — убран мёртвый код (return len() после return entry).
- core/mods.py — добавлен обязательный handle в TranslationEntry, импорт EntryType,
  поле ModScan.unsupported.
- tests/test_async_engine.py — FakeProvider.is_configured(); проверка завершения
  через processed_files вместо несуществующего done.

## M11 — async-перевод в UI (фикс зависания «Перевести всё»)
Проблема: батч-перевод выполнялся через синхронный `engine.translate_entry()`
в главном потоке. При переводе через Gemini (10+ секунд на запрос) весь Qt-UI
замирал («нажимаю Перевод → окно перестало отвечать»).

Решение:
- ui/pages/editor.py: `_translate_all()` теперь вызывает `engine.run_async()`.
  Прогресс приходит через Qt-сигналы (queued в главный поток). Добавлены кнопка
  «Остановить» (graceful cancel) и статус-бар в главном окне (`set_status`).
- Каждый вызов провайдера выполняется в worker-thread; окно всегда отзывчиво.
- Тесты tests/test_async_engine.py и tests/test_async_ui.py.

## M12 — полная русификация интерфейса
Весь пользовательский интерфейс переведён на русский язык:
- ui/main_window.py — сайдбар: Главная / Перевод / Словарь / Настройки; статус-бар «Готово».
- ui/pages/dashboard.py — «Главная», «Перевести мод», языки «С»/«На», кнопки,
  плитки статистики, инфо о проекте, диалоги и тосты импорта.
- ui/pages/editor.py — «Перевод», поиск, фильтры, «Перевести всё»/«Остановить»/«Экспорт…»,
  статусы (Новый/Переведено/Словарь/AI/Проверка/Готово/Закрыто), меню экспорта,
  диалоги и тосты; ошибки ImportWorker на русском.
- ui/pages/settings_page.py — «Настройки», «Оформление», «Провайдер перевода»,
  «Проверка», «Сохранить настройки» и тост.
- ui/pages/dictionary_page.py — «Словарь», поиск, счётчик.

Дефолт языка перевода: Английский → Русский (выбор по коду, не по индексу).
Фильтр редактора переписан на проверку объекта записи (не разбор текста статуса) —
устойчиво к локализации.
Также убран UTF-8 BOM из __init__.py файлов (созданных через PowerShell Out-File).

## Прогон тестов (все зелёные)
- test_core.py         — CORE OK (валидация + XML loca)
- test_services.py     — SERVICES OK (словарь, движок dictionary-first, provider+cache, placeholder-guard, batch)
- test_pak.py          — PAK OK (round-trip LZ4, bad signature, ImportWorker pak+zip)
- test_ui.py           — UI OK (offscreen: навигация, редактор, фильтры)
- test_launch.py       — LAUNCH OK (полный запуск, чистое завершение)
- test_unique_tav.py   — TAV OK (регресс: 125 локализаций, key overlap 125/125)
- test_async_engine.py — ASYNC OK (прогресс 2/2, 100%, сигналы не блокируют UI)
- test_async_ui.py     — ASYNC-UI OK (9 progress-сигналов, 8/8 переведено, UI не блокируется)

## Запуск
```
pip install -r requirements.txt
python main.py
```

## Замечания
- Проект под git; репозиторий привязан к https://github.com/Dafred04/BG3-Translator.git
