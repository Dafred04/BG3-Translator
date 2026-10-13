"""Append fix note to Docs/PROGRESS.md."""
from pathlib import Path

path = Path("C:/Users/user/Desktop/BG3_ModTranslator_New/Docs/PROGRESS.md")
note = """
## Патч 1 (bugfix: упаковка unique_tav + .loca/.xml):
- Причина поломки реального .pak (KAZSTRA_UniqueTav, 507 файлов): неверный разбор заголовка списка файлов v18. LSLib ReadCompressedFileList: numFiles u32 @off, compressedSize u32 @off+4, LZ4 payload @off+8 (без префикса store_size).
- Фикс: читаем по спецификации, валидируем num_files*272, раскрываем бинарные .loca (LSLib LocaResource), распознаём плоский XML <content contentuid> (как в упаковках), иначе translated_string/content.
- Результат: 125 локализаций, handle-наборы xml и loca полностью совпадают. Регресс-тест tests/test_unique_tav.py PASSED.
- Тесты: test_core / test_services / test_pak / test_ui / test_launch + test_unique_tav - все зелёные.
"""
text = path.read_text(encoding="utf-8")
if "Патч 1 (bugfix" not in text:
    path.write_text(text + note, encoding="utf-8")
    print("progress updated")
else:
    print("already present")
