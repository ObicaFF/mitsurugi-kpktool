import sys
import kpktool, b04tool, e3tool


def diff(kpk_a, exe_a, kpk_b, exe_b, show_text=True):
    ua = kpktool.unpack_exact(kpk_a, exe_a)
    ub = kpktool.unpack_exact(kpk_b, exe_b)
    a = {f['key']: bytes(f['raw_bytes']) for f in ua['files']}
    b = {f['key']: bytes(f['raw_bytes']) for f in ub['files']}
    out = []
    for k in sorted(set(a) | set(b)):
        if k not in a:
            out.append(('+', k, 'only in B'))
        elif k not in b:
            out.append(('-', k, 'only in A'))
        elif a[k] != b[k]:
            note = '%d -> %d bytes' % (len(a[k]), len(b[k]))
            if show_text:
                t = kpktool._sniff(a[k])
                if t in ('b04', 'e3'):
                    tool = b04tool if t == 'b04' else e3tool
                    try:
                        sa = tool.parse(a[k]).get('strings', [])
                        sb = tool.parse(b[k]).get('strings', [])
                        changes = [(i, sa[i], sb[i]) for i in range(min(len(sa), len(sb))) if sa[i] != sb[i]]
                        note += ' | %d string changes' % len(changes)
                    except Exception:
                        pass
            out.append(('~', k, note))
    return out


if __name__ == '__main__':
    if len(sys.argv) < 5:
        print('usage: kpkdiff.py A.kpk A.exe B.kpk B.exe')
        sys.exit(1)
    rows = diff(*sys.argv[1:5])
    for sign, k, note in rows:
        print('%s %08x  %s' % (sign, k, note))
    print('\n%d files differ' % len(rows))
