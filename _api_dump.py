import io, sys, inspect, dataclasses, enum
sys.path.insert(0, 'src')
out = []
def w(s=''):
    out.append(str(s))

from bg3_translator import config as C
w('=== CONFIG ===')
for name in dir(C):
    if name.startswith('_'):
        continue
    obj = getattr(C, name)
    if inspect.isclass(obj) and dataclasses.is_dataclass(obj):
        w('[dataclass] %s:' % name)
        for f in dataclasses.fields(obj):
            w('    %s: %s = %r' % (f.name, f.type, f.default))
    elif name.isupper() and isinstance(obj, (list, tuple)):
        w('%s = %r' % (name, obj))

from bg3_translator.models import translation as T
w('=== MODELS ===')
for cls_name in ['TranslationEntry','DictionaryEntry','ModMetadata','TranslationProject','TranslationStatus','EntryType']:
    obj = getattr(T, cls_name, None)
    if obj is None:
        w('%s: MISSING' % cls_name); continue
    if dataclasses.is_dataclass(obj):
        w('[dataclass] %s:' % cls_name)
        for f in dataclasses.fields(obj):
            w('    %s: %s' % (f.name, f.type))
        for m in ['is_translated','update_timestamps','update_stats','to_dict','from_dict','has_validation_errors']:
            if hasattr(obj, m):
                try: w('    method %s%s' % (m, inspect.signature(getattr(obj,m))))
                except Exception: pass
    elif isinstance(obj, type) and issubclass(obj, enum.Enum):
        w('[enum] %s: %r' % (cls_name, [(e.name,e.value) for e in obj]))

from bg3_translator.services import engine as E
w('=== ENGINE ===')
w('StageId: %r' % [(e.name,e.value) for e in E.StageId])
w('STAGE_TEXT: %r' % {str(k):v for k,v in E.STAGE_TEXT.items()})
w('JobProgress fields:')
for f in dataclasses.fields(E.JobProgress):
    w('    %s: %s' % (f.name, f.type))
w('Engine methods: %r' % [m for m in dir(E.TranslationEngine) if not m.startswith('__')])
for m in ['run_async','cancel','set_provider','translate_entry','translate_batch','is_running']:
    if hasattr(E.TranslationEngine, m):
        try: w('    %s%s' % (m, inspect.signature(getattr(E.TranslationEngine,m))))
        except Exception: pass

from bg3_translator.services import providers as P
w('=== PROVIDERS ===')
w('funcs: %r' % [n for n in dir(P) if not n.startswith('_') and inspect.isfunction(getattr(P,n))])
if hasattr(P,'get_provider'):
    w('get_provider%s' % inspect.signature(P.get_provider))
for cn in dir(P):
    obj = getattr(P, cn)
    if inspect.isclass(obj) and hasattr(obj,'translate'):
        w('class %s: name=%r methods=%r' % (cn, getattr(obj,'name',None), [m for m in dir(obj) if not m.startswith('_')]))

from bg3_translator.ui import state as S
w('=== STATE ===')
w('funcs: %r' % [n for n in dir(S) if not n.startswith('_')])
for n in dir(S):
    obj = getattr(S, n)
    if inspect.isclass(obj):
        w('class %s attrs: %r' % (n, [a for a in dir(obj) if not a.startswith('_')]))

from bg3_translator.ui import theme as TH
w('=== THEME ===')
w('exports: %r' % [n for n in dir(TH) if not n.startswith('_')])
if hasattr(TH,'Palette'):
    w('Palette fields: %r' % [f for f in dir(TH.Palette) if not f.startswith('_')])

w('=== MAIN.PY ===')
w(io.open('main.py', encoding='utf-8').read())

io.open('_api_out.txt','w',encoding='utf-8').write('\n'.join(out))
print('WROTE %d lines' % len(out))
