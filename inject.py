import os, sys, json, glob
import kpktool, b04tool, e3tool


def build_text_replacements(unpacked, en2ru, e3_dir):
    by_key = {f['key']: f for f in unpacked['files']}
    content2key = {bytes(f['raw_bytes']): f['key'] for f in unpacked['files']}
    repl = {}

    for f in unpacked['files']:
        raw = bytes(f['raw_bytes'])
        if raw[:4] != b'\x04\x00\x00\x00':
            continue
        m = b04tool.parse(raw)
        new = [en2ru.get(s, s) for s in m['strings']]
        if new == m['strings']:
            continue
        b04tool.set_strings(m, new)
        rebuilt = b04tool.build(m)
        assert b04tool.parse(rebuilt)['strings'] == new
        repl[f['key']] = rebuilt

    for path in sorted(glob.glob(os.path.join(e3_dir, '*.e3'))):
        raw = open(path, 'rb').read()
        key = content2key.get(raw)
        if key is None:
            continue
        m = e3tool.parse(raw)
        if not m['has_block']:
            continue
        new = [en2ru.get(s, s) for s in m['strings']]
        if new == m['strings']:
            continue
        e3tool.set_strings(m, new)
        rebuilt = e3tool.build(m)
        assert e3tool.parse(rebuilt)['strings'] == new
        repl[key] = rebuilt

    return repl


def build_patch(kpk_path, exe_path, out_kpk, out_exe,
                en2ru=None, e3_dir=None, binary_replacements=None):
    u = kpktool.unpack_exact(kpk_path, exe_path)
    repl = {}
    if en2ru is not None and e3_dir is not None:
        repl.update(build_text_replacements(u, en2ru, e3_dir))
    if binary_replacements:
        for k, b in binary_replacements.items():
            repl[k] = b
    new_kpk, patches = kpktool.repack_multi(u, repl)
    new_exe = kpktool.patch_exe_directory(open(exe_path, 'rb').read(), patches)
    open(out_kpk, 'wb').write(new_kpk)
    open(out_exe, 'wb').write(new_exe)

    out = kpktool.unpack_exact(out_kpk, out_exe)
    by = {f['key']: bytes(f['raw_bytes']) for f in out['files']}
    bad = sum(1 for k, b in repl.items() if by.get(k) != b)
    return dict(replaced=len(repl), verify_mismatch=bad,
                kpk=len(new_kpk), exe=len(new_exe))


if __name__ == '__main__':
    if len(sys.argv) < 7:
        print('usage: inject.py data0.kpk mitsurugi.exe en2ru.json e3_dir/ out.kpk out.exe '
              '[key=file ...]')
        sys.exit(1)
    kpk, exe, mapj, e3dir, out_kpk, out_exe = sys.argv[1:7]
    en2ru = json.load(open(mapj, encoding='utf-8'))
    binr = {}
    for arg in sys.argv[7:]:
        k, _, fn = arg.partition('=')
        binr[int(k, 16)] = open(fn, 'rb').read()
    rep = build_patch(kpk, exe, out_kpk, out_exe, en2ru=en2ru, e3_dir=e3dir,
                      binary_replacements=binr or None)
    print(rep)
    sys.exit(0 if rep['verify_mismatch'] == 0 else 2)
