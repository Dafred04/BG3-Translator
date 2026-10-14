import glob
bad = []
# mojibake signatures: double-encoded Cyrillic in UTF-8 file read as cp1251->utf8
sigs = ['Р°', 'РЅ', 'Рѕ', 'СЂ', 'вЂ', 'Рё', 'СЃ', 'Рµ', 'С‚', 'РІ', 'Рє', 'Рј', 'Рї', 'Сѓ']
for f in glob.glob('src/**/*.py', recursive=True) + glob.glob('tests/**/*.py', recursive=True):
    t = open(f, encoding='utf-8').read()
    hits = [s for s in sigs if s in t]
    if hits:
        bad.append((f, len(hits)))
if bad:
    print('MOJIBAKE_FILES:')
    for f, n in bad:
        print(f'  {f} ({n} signatures)')
else:
    print('MOJIBAKE_FILES: NONE')
