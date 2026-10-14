"""Audit: dump exact contracts + detect damage."""
import ast, glob, io, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

print("=== SYNTAX ===")
for f in sorted(glob.glob('src/**/*.py', recursive=True)) + ['main.py']:
    try:
        ast.parse(io.open(f, encoding='utf-8').read())
    except SyntaxError as e:
        print(f"SYNTAX ERROR {f}: {e}")

print("\n=== MOJIBAKE (double-encoded UTF-8 markers) ===")
MOJI = ['Р°','Р±','РІ','СЂ','С‚','вЂ','Ã©','Ð¿']
for f in sorted(glob.glob('src/**/*.py', recursive=True)) + ['main.py']:
    txt = io.open(f, encoding='utf-8').read()
    hits = sum(txt.count(m) for m in MOJI)
    if hits:
        print(f"  {f}: ~{hits} suspicious sequences")

print("\n=== UI FILE SIZES ===")
for f in sorted(glob.glob('src/bg3_translator/ui/**/*.py', recursive=True)):
    n = len(io.open(f, encoding='utf-8').read().splitlines())
    print(f"  {f}: {n} lines")

print("\n=== CONFIG ===")
try:
    from bg3_translator import config as C
    import dataclasses
    if hasattr(C, 'Settings') and dataclasses.is_dataclass(C.Settings):
        for fld in dataclasses.fields(C.Settings):
            print(f"  {fld.name} = {fld.default!r}")
    for nm in ('LANGUAGES','LANGUAGE_NAMES','LANGS'):
        if hasattr(C, nm):
            print(f"  {nm} = {getattr(C, nm)}")
except Exception as e:
    print("  ERR", e)

print("\n=== PROVIDERS API ===")
try:
    from bg3_translator.services import providers as P
    print("  names:", [n for n in dir(P) if n[0].isupper()])
    for cls in ('GeminiProvider','OpenAIProvider','GoogleFreeProvider'):
        if hasattr(P, cls):
            c = getattr(P, cls)
            print(f"  {cls}:", [m for m in dir(c) if not m.startswith('_')])
    for fn in ('get_provider','list_models','available_providers'):
        if hasattr(P, fn):
            import inspect
            print(f"  {fn}{inspect.signature(getattr(P, fn))}")
except Exception as e:
    print("  ERR", e)

print("\n=== ENGINE API ===")
try:
    from bg3_translator.services.engine import TranslationEngine, JobProgress
    import inspect, dataclasses
    print("  methods:", [m for m in dir(TranslationEngine) if not m.startswith('_')])
    for sig in ('run_async','set_provider','cancel','translate_entry','translate_batch'):
        if hasattr(TranslationEngine, sig):
            print(f"    {sig}{inspect.signature(getattr(TranslationEngine, sig))}")
    if dataclasses.is_dataclass(JobProgress):
        print("  JobProgress:", [f.name for f in dataclasses.fields(JobProgress)])
    from bg3_translator.services import engine as E
    print("  STAGE:", [n for n in dir(E) if 'STAGE' in n])
except Exception as e:
    print("  ERR", e)

print("\n=== STATE API ===")
try:
    from bg3_translator.ui.state import AppState
    print("  attrs:", [m for m in dir(AppState) if not m.startswith('_')])
except Exception as e:
    print("  ERR", e)

print("\n=== THEME API ===")
try:
    from bg3_translator.ui import theme as T
    print("  names:", [n for n in dir(T) if not n.startswith('_')])
    if hasattr(T, 'Palette'):
        import dataclasses
        print("  Palette:", [f.name for f in dataclasses.fields(T.Palette)])
    if hasattr(T, 'build_stylesheet'):
        import inspect
        print("  build_stylesheet:", inspect.signature(T.build_stylesheet))
except Exception as e:
    print("  ERR", e)

print("\n=== MODELS ===")
try:
    from bg3_translator.models import translation as M
    import dataclasses
    for cls in ('TranslationEntry','DictionaryEntry','ModMetadata','TranslationProject'):
        if hasattr(M, cls) and dataclasses.is_dataclass(getattr(M, cls)):
            print(f"  {cls}:", [f.name for f in dataclasses.fields(getattr(M, cls))])
    import inspect
    if hasattr(M, 'TranslationProject'):
        print("  Project methods:", [m for m in dir(M.TranslationProject) if not m.startswith('_')])
    print("  EntryType:", [e.name for e in M.EntryType] if hasattr(M, 'EntryType') else 'n/a')
    print("  TranslationStatus:", [e.name for e in M.TranslationStatus] if hasattr(M, 'TranslationStatus') else 'n/a')
except Exception as e:
    print("  ERR", e)
