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
- [x] M10: восстановление ядра после компактификации контекста (см. ниже)

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

## Прогон тестов (все зелёные)
- test_core.py        — CORE OK (валидация + XML loca)
- test_services.py    — SERVICES OK (словарь, движок dictionary-first, provider+cache, placeholder-guard, batch)
- test_pak.py         — PAK OK (round-trip LZ4, bad signature, ImportWorker pak+zip)
- test_ui.py          — UI OK (offscreen: навигация, редактор, фильтры)
- test_launch.py      — LAUNCH OK (полный запуск, чистое завершение)
- test_unique_tav.py  — TAV OK (регресс: 125 локализаций, key overlap 125/125)
- test_async_engine.py — ASYNC OK (прогресс 2/2, 100%, сигналы не блокируют UI)

## Следующие шаги
1. Подключить async-движок к UI (кнопка "Перевести" / "Перевести всё" → run_async + экран прогресса).
2. Восстановить выбор версии Gemini + получение списка моделей через API.
3. Полный русский UI во всех страницах (сейчас частично).
4. Онбординг первого запуска.
5. Диагностика: таблица причин пропусков/ошибок по файлам.

## Запуск
```
pip install -r requirements.txt
python main.py
```

## Замечания
- Проект под git; репозиторий привязан к https://github.com/Dafred04/BG3-Translator.git
