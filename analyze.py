import sys, struct, json, io
from collections import Counter
import kpktool, b04tool, e3tool, fmtool


def analyze(kpk_path, exe_path):
    u = kpktool.unpack_exact(kpk_path, exe_path)
    types = Counter()
    texts = {}
    atlases = []
    fonts = []
    for f in u['files']:
        raw = bytes(f['raw_bytes'])
        t = kpktool._sniff(raw)
        types[t] += 1
        key = '%08x' % f['key']
        if t == 'b04':
            try:
                s = b04tool.parse(raw)['strings']
                if s: texts[key] = ('b04', s)
            except Exception:
                pass
        elif t == 'e3':
            try:
                m = e3tool.parse(raw)
                if m['has_block'] and m['strings']:
                    texts[key] = ('e3', m['strings'])
            except Exception:
                pass
        elif t == 'tex':
            w = struct.unpack_from('<H', raw, 12)[0]
            h = struct.unpack_from('<H', raw, 14)[0]
            atlases.append((key, 'tex', w, h, len(raw) - w * h * 4))
        elif t == 'dds':
            w = struct.unpack_from('<I', raw, 16)[0]
            h = struct.unpack_from('<I', raw, 12)[0]
            atlases.append((key, 'dds', w, h, raw[84:88].decode('latin1', 'replace')))
        elif raw[:2] == b'FM':
            m = fmtool.parse(raw)
            fonts.append((key, m['glyph_count'], {b: (p['count'], p['dims']) for b, p in m['pages'].items()}))
    total_lines = sum(len(s) for _, s in texts.values())
    return dict(files=len(u['files']), tail=len(u['tail']), types=dict(types),
                text_files=len(texts), text_lines=total_lines,
                texts=texts, atlases=atlases, fonts=fonts)


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print('usage: analyze.py data0.kpk mitsurugi.exe [dump_text.json]')
        sys.exit(1)
    r = analyze(sys.argv[1], sys.argv[2])
    print('files: %d (+%d byte tail)' % (r['files'], r['tail']))
    print('types:', r['types'])
    print('text-bearing files: %d   total lines: %d' % (r['text_files'], r['text_lines']))
    print('fonts:')
    for key, gc, pages in r['fonts']:
        print('  %s  glyphs=%d  pages=%s' % (key, gc, pages))
    print('atlases: %d' % len(r['atlases']))
    for a in r['atlases'][:12]:
        print('  ', a)
    if len(sys.argv) > 3:
        flat = {}
        for key, (t, strs) in r['texts'].items():
            for i, s in enumerate(strs):
                flat['%s[%d]' % (key, i)] = s
        json.dump(flat, io.open(sys.argv[3], 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('dumped %d strings -> %s' % (len(flat), sys.argv[3]))
