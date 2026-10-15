"""Командная строка: пакетный перевод модов без GUI.

    python -m bg3_translator.cli translate mod1.pak mod2.zip --to ru -o out/
    python -m bg3_translator.cli inspect mod.pak
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import List, Optional

from .models.translation import TranslationProject
from .services import exporter
from .services.dictionary import DictionaryStore
from .services.engine import EngineOptions, TranslationEngine
from .services.importer import ImportFailure, import_mod
from .services.providers import get_provider


def _settings():
    try:
        from .config import PATHS, get_settings
        return get_settings(), Path(PATHS.cache_dir)
    except Exception:
        import tempfile
        return None, Path(tempfile.gettempdir())


def _build_provider(args, settings):
    name = args.provider or (settings.default_provider if settings else "gemini")
    cfg = settings.providers.get(name) if settings else None
    key = args.api_key or os.environ.get("BG3TR_API_KEY") or (cfg.api_key if cfg else "")
    try:
        from .services import keystore
        key = key or keystore.get_api_key(name)
    except Exception:
        pass
    return get_provider(name, api_key=key, model=args.model or (cfg.model if cfg else ""),
                        base_url=args.base_url or (cfg.base_url if cfg else ""),
                        timeout=settings.timeout if settings else 60)


def cmd_inspect(args) -> int:
    rc = 0
    for path in args.inputs:
        try:
            res = import_mod(path, args.source, args.to)
        except ImportFailure as exc:
            print(f"{path}: ОШИБКА — {exc}")
            rc = 1
            continue
        m = res.metadata
        print(f"{path}\n  мод: {m.name} {m.version}  автор: {m.author or '—'}  папка: {m.folder or '—'}")
        print(f"  языки: {', '.join(res.languages) or '—'}  источник: {res.source_folder or '—'}  "
              f"готовый перевод: {res.target_folder or 'нет'} ({res.prefilled} строк)")
        print(f"  строк: {len(res.entries)}  символов: {sum(len(e.source_text) for e in res.entries)}")
        for d in res.diagnostics:
            print(f"  ! {d}")
    return rc


def cmd_translate(args) -> int:
    settings, cache = _settings()
    dictionary = DictionaryStore(cache / "dictionary.db")
    provider = _build_provider(args, settings)
    opts = EngineOptions(batch_size=args.batch, workers=args.workers, fuzzy_threshold=args.fuzzy,
                         validate_placeholders=not args.no_validate)
    engine = TranslationEngine(dictionary, provider, opts)
    out_dir = Path(args.output or ".")
    out_dir.mkdir(parents=True, exist_ok=True)
    rc = 0
    for path in args.inputs:
        print(f"\n== {path}")
        try:
            res = import_mod(path, args.source, args.to, progress=lambda m: print("  " + m))
        except ImportFailure as exc:
            print(f"  ОШИБКА: {exc}")
            rc = 1
            continue
        project: TranslationProject = res.to_project(args.source, args.to)

        def show(pg):
            print(f"\r  {pg.stage_text}: {pg.percent:3d}%  {pg.done}/{pg.total}  "
                  f"словарь:{pg.from_dictionary} ошибок:{pg.failed} на проверку:{pg.review}", end="", flush=True)

        pg = engine.translate_batch(project.entries, show, res.metadata.name)
        print()
        project.update_stats()
        if pg.message.startswith("aborted:"):
            print("  " + pg.message[len("aborted:"):].strip())
            rc = 2
        elif engine.first_error and pg.failed:
            print(f"  Часть строк не переведена: {engine.first_error}")
            rc = 2
        rep = exporter.report(project)
        print(f"  переведено {rep.translated}/{rep.total}, ошибок {rep.with_errors}, предупреждений {rep.with_warnings}, "
              f"отправлено символов: {pg.chars_sent}")
        out = out_dir / exporter.default_pak_name(project)
        if args.format == "pak":
            exporter.export_pak(project, out, fallback_to_source=not args.no_fallback)
        elif args.format == "loca":
            out = out.with_suffix(".loca")
            out.write_bytes(exporter.export_loca_bytes(project, not args.no_fallback))
        else:
            out = out.with_suffix(".xml")
            out.write_text(exporter.export_xml_text(project, not args.no_fallback), encoding="utf-8")
        print(f"  сохранено: {out}")
    return rc


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="bg3tr", description="BG3 Mod Translator (CLI)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("translate", "inspect"):
        p = sub.add_parser(name)
        p.add_argument("inputs", nargs="+", help=".pak / .zip / папка / .xml / .loca")
        p.add_argument("--from", dest="source", default="en")
        p.add_argument("--to", default="ru")
    t = sub.choices["translate"]
    t.add_argument("-o", "--output", help="папка результата")
    t.add_argument("--format", choices=["pak", "loca", "xml"], default="pak")
    t.add_argument("--provider", choices=["gemini", "openai_compatible", "google_free"])
    t.add_argument("--api-key")
    t.add_argument("--model")
    t.add_argument("--base-url")
    t.add_argument("--batch", type=int, default=25)
    t.add_argument("--workers", type=int, default=3)
    t.add_argument("--fuzzy", type=float, default=0.0, help="порог нечётких совпадений 0.8..0.99")
    t.add_argument("--no-fallback", action="store_true", help="не включать непереведённое (оригинал) в результат")
    t.add_argument("--no-validate", action="store_true")
    args = ap.parse_args(argv)
    return cmd_inspect(args) if args.cmd == "inspect" else cmd_translate(args)


if __name__ == "__main__":
    sys.exit(main())
