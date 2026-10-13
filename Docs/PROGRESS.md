# BG3 Mod Translator v2 — Progress

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
- Режим апгрейда: переиспользование UUID/Folder старого CHS-пака
- Экспорт: .pak / .xml / .zip (BG3MM-совместимый)
- Настройки: провайдеры, API-ключи, пакетный размер, строгий режим

## Архитектура
```
src/bg3_translator/
  config.py          — пути, настройки, языки ✅
  models/translation.py — TranslationEntry, DictionaryEntry, ModMetadata, TranslationProject ✅
  core/              — pak/loca/xml обработка, валидация
  services/          — translation providers, dictionary, project store
  ui/                — PySide6: главный экран, редактор, настройки
  utils/             — helpers
```

## Milestones
- [x] M1: Аудит старой версии, проектирование архитектуры
- [x] M2: config.py + models (проверено: round-trip сериализация)
- [x] M3: core — XML локализации (locaxml.py), валидация плейсхолдеров (validation.py) ✅ tests/test_core.py passed
- [x] M4: services — словарь (SQLite), провайдеры перевода (Google Free + OpenAI-совместимые) ✅ tests/test_services.py passed (6 проверок: dictionary, engine dictionary-first, provider+cache, placeholder guard, batch progress)
- [x] M5: UI — дизайн-система (theme.py, widgets.py), главное окно (sidebar-nav, toast), страницы Dashboard/Editor/Dictionary/Settings ✅ tests/test_ui.py passed (offscreen)
- [x] M6: core/pak.py — чтение LSPK v17/v18 (LZ4/Zlib/Zstd), writer, интеграция импорта (.pak/.zip/.xml/папка) и экспорта (.xml/.pak) ✅ tests/test_pak.py passed (round-trip, bad signature, ImportWorker pak+zip)
- [x] M7: Финальное тестирование ✅ tests/test_launch.py (запуск через main.main(), offscreen, чистое завершение), requirements.txt, README.md

## Тесты (финальный прогон — все зелёные)
- M2: `python -c "from bg3_translator.models import *; ..."` — OK (round-trip)
- M3: `python tests\test_core.py` — OK (validation + locaxml round-trip)
- M4: `python tests\test_services.py` — OK (dictionary, engine dictionary-first, provider+cache, placeholder guard, batch progress)
- M5: `python tests\test_ui.py` — OK (offscreen: nav, pages, editing, validation, filters)
- M6: `python tests\test_pak.py` — OK (pak round-trip LZ4, bad signature, ImportWorker pak+zip end-to-end)
- M7: `python tests\test_launch.py` — OK (полный запуск приложения, чистое завершение)

## Итог
Приложение полностью функционально: импорт .pak/.zip/.xml/папки → редактор с поиском/фильтрами → словарь + автоперевод (Google Free / OpenAI-совместимые) → валидация плейсхолдеров → экспорт .xml/.pak. Современный UI: sidebar-навигация, карточки, toast-уведомления, light/dark тема, прогресс батч-перевода, фоновый импорт.

## Замечания
- git не установлен в системе — контроль версий через PROGRESS.md
## Патч 1 (bugfix: упаковка unique_tav + .loca/.xml):
- Причина поломки реального .pak (KAZSTRA_UniqueTav, 507 файлов): неверный разбор заголовка списка файлов v18. LSLib ReadCompressedFileList: numFiles u32 @off, compressedSize u32 @off+4, LZ4 payload @off+8 (без префикса store_size).
- Фикс: читаем по спецификации, валидируем num_files*272, раскрываем бинарные .loca (LSLib LocaResource), распознаём плоский XML <content contentuid> (как в упаковках), иначе translated_string/content.
- Результат: 125 локализаций, handle-наборы xml и loca полностью совпадают. Регресс-тест tests/test_unique_tav.py PASSED.
- Тесты: test_core / test_services / test_pak / test_ui / test_launch + test_unique_tav - все зелёные.
