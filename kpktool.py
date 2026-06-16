import struct, zlib, os, sys, json

EXE_DIR_VA   = 0x004BFE50
EXE_IMGBASE  = 0x00400000
RDATA_RAW    = 0x000A9000
RDATA_VA     = 0x000AA000
EXE_DIR_FOFF = EXE_DIR_VA - RDATA_VA - EXE_IMGBASE + RDATA_RAW
ENT_SIZE     = 24
ALIGN        = 8
ZLIB_2ND     = (0x01, 0x9C, 0xDA)


def read_directory(exe_bytes):
    o = EXE_DIR_FOFF
    out = []
    prev = -1
    k = 0
    while True:
        rec = exe_bytes[o + k * ENT_SIZE: o + (k + 1) * ENT_SIZE]
        if len(rec) < ENT_SIZE:
            break
        key, a, b, off, d, flags = struct.unpack('<6I', rec)
        if k == 0 and key == 0 and off == 0:
            k += 1
            continue
        if key <= prev:
            break
        prev = key
        out.append(dict(idx=k, key=key, a=a, b=b, off=off, d=d, flags=flags))
        k += 1
    return out


def entry_offset_in_exe(slot_idx):
    return EXE_DIR_FOFF + slot_idx * ENT_SIZE


def _zlib_consumed(buf, off):
    do = zlib.decompressobj()
    out = do.decompress(buf[off:])
    consumed = len(buf) - off - len(do.unused_data)
    return consumed, len(out)


def _stored_len(kpk, e):
    if e['b']:
        consumed, _ = _zlib_consumed(kpk, e['off'])
        return consumed
    return e['a']


def _present(kpk, e):
    off, b = e['off'], e['b']
    if off >= len(kpk):
        return False
    if b:
        if not (kpk[off:off + 1] == b'\x78' and len(kpk) > off + 1
                and kpk[off + 1] in ZLIB_2ND):
            return False
        if off + b > len(kpk):
            return False
    else:
        if off + e['a'] > len(kpk):
            return False
    return True


def physical_files(kpk, directory):
    present = [e for e in directory if _present(kpk, e)]
    ivs = []
    for e in present:
        sl = _stored_len(kpk, e)
        ivs.append((e['off'], e['off'] + sl, sl, e))
    ivs.sort(key=lambda x: (x[0], -x[1]))
    top = []
    cur_end = -1
    for s, en, sl, e in ivs:
        if s >= cur_end:
            top.append(dict(off=s, end=en, stored=sl, entry=e))
            cur_end = en
        elif en > cur_end:
            top[-1]['end'] = en
            top[-1]['stored'] = en - top[-1]['off']
            cur_end = en
    return top


def unpack(kpk_path, exe_path):
    kpk = open(kpk_path, 'rb').read()
    exe = open(exe_path, 'rb').read()
    directory = read_directory(exe)
    top = physical_files(kpk, directory)
    files = []
    cursor = 0
    for i, t in enumerate(top):
        off, end = t['off'], t['end']
        nxt_start = top[i + 1]['off'] if i + 1 < len(top) else None
        e = t['entry']
        comp = bool(e['b'])
        on_disk = kpk[off:end]
        raw = zlib.decompress(on_disk) if comp else on_disk
        pad = kpk[end:nxt_start] if nxt_start is not None else b''
        files.append(dict(
            key=e['key'], off=off, comp=comp, raw_bytes=raw,
            on_disk_len=len(on_disk), pad_len=len(pad), pad=pad,
            entry_idx=e['idx'], a=e['a'], b=e['b'], d=e['d'], flags=e['flags']))
        cursor = nxt_start if nxt_start is not None else end
    return dict(directory=directory, files=files, tail=kpk[cursor:], kpk_size=len(kpk))


def unpack_exact(kpk_path, exe_path):
    u = unpack(kpk_path, exe_path)
    kpk = open(kpk_path, 'rb').read()
    for f in u['files']:
        f['_ondisk'] = kpk[f['off']: f['off'] + f['on_disk_len']]
    return u


def _pad_to_align(n, align=ALIGN):
    return (-n) % align


def _reconstruct_on_disk(f):
    if '_ondisk' in f:
        return f['_ondisk']
    return zlib.compress(f['raw_bytes'], 9) if f['comp'] else f['raw_bytes']


def repack_multi(unpacked, replacements):
    import bisect
    files = unpacked['files']
    directory = unpacked.get('directory', [])
    out = bytearray()
    dir_patches = []
    extents = []
    for f in files:
        new_off = len(out)
        old_off = f['off']
        old_end = old_off + f['on_disk_len']
        if f['key'] in replacements:
            new_raw = replacements[f['key']]
            if f['comp']:
                payload = zlib.compress(new_raw, 9)
                new_b = len(payload)
            else:
                payload = new_raw
                new_b = 0
            out += payload
            out += b'\x00' * _pad_to_align(len(out))
            dir_patches.append(dict(entry_idx=f['entry_idx'], off=new_off,
                                    a=len(new_raw), b=new_b))
        else:
            out += _reconstruct_on_disk(f)
            out += f['pad']
            dir_patches.append(dict(entry_idx=f['entry_idx'], off=new_off,
                                    a=f['a'], b=f['b']))
        extents.append((old_off, old_end, new_off))
    file_keys = set(f['key'] for f in files)
    extents.sort()
    starts = [e[0] for e in extents]
    for e in directory:
        if e['key'] in file_keys:
            continue
        j = bisect.bisect_right(starts, e['off']) - 1
        if 0 <= j < len(extents):
            o0, o1, no = extents[j]
            if o0 <= e['off'] < o1:
                dir_patches.append(dict(entry_idx=e['idx'], off=e['off'] + (no - o0),
                                        a=e['a'], b=e['b']))
    out += unpacked['tail']
    return bytes(out), dir_patches


def patch_exe_directory(exe_bytes, dir_patches):
    exe = bytearray(exe_bytes)
    for p in dir_patches:
        base = entry_offset_in_exe(p['entry_idx'])
        struct.pack_into('<I', exe, base + 0x04, p['a'])
        struct.pack_into('<I', exe, base + 0x08, p['b'])
        struct.pack_into('<I', exe, base + 0x0C, p['off'])
    return bytes(exe)


def _sniff(b):
    if b[:4] == b'DDS ': return 'dds'
    if b[:2] == b'BM': return 'bmp'
    if b[:4] == b'W9A2': return 'w9a2'
    if b[:4] == b'CMA2': return 'cma2'
    if b[:4] == b'\x89PNG': return 'png'
    if b[:4] == b'OggS': return 'ogg'
    if b[:4] == b'\x00\x00\x02\x00': return 'tex'
    if b[:4] == b'E3\x0e\x00': return 'e3'
    if b[:4] == b'\xd0\xcf\x11\xe0': return 'ole'
    if len(b) >= 4:
        t = struct.unpack_from('<I', b, 0)[0]
        if t == 0x14: return 'b14'
        if t == 0x04: return 'b04'
    return 'bin'


def cmd_unpack(kpk, exe, outdir):
    u = unpack_exact(kpk, exe)
    os.makedirs(outdir, exist_ok=True)
    manifest = []
    for i, f in enumerate(u['files']):
        name = '%05d_%08x.%s' % (i, f['key'], _sniff(f['raw_bytes']))
        open(os.path.join(outdir, name), 'wb').write(f['raw_bytes'])
        manifest.append(dict(i=i, key='%08x' % f['key'], off=f['off'],
                             comp=f['comp'], raw=len(f['raw_bytes']),
                             stored=f['on_disk_len'], entry_idx=f['entry_idx'],
                             flags=f['flags'], name=name))
    open(os.path.join(outdir, 'tail.bin'), 'wb').write(u['tail'])
    json.dump(dict(files=manifest, tail_len=len(u['tail']), kpk_size=u['kpk_size']),
              open(os.path.join(outdir, 'manifest.json'), 'w'), indent=1)
    sys.stderr.write('unpacked %d files (+%d tail) -> %s\n' % (len(u['files']), len(u['tail']), outdir))


def cmd_verify(kpk, exe):
    u = unpack_exact(kpk, exe)
    rebuilt, _ = repack_multi(u, {})
    orig = open(kpk, 'rb').read()
    same = rebuilt == orig
    sys.stderr.write('orig=%d rebuilt=%d IDENTICAL=%s\n' % (len(orig), len(rebuilt), same))
    return same


def cmd_replace(kpk, exe, key_hex, newfile, out_kpk, out_exe):
    key = int(key_hex, 16)
    u = unpack_exact(kpk, exe)
    if not any(f['key'] == key for f in u['files']):
        sys.stderr.write('key %08x not in this kpk\n' % key)
        return False
    new_kpk, patches = repack_multi(u, {key: open(newfile, 'rb').read()})
    open(out_kpk, 'wb').write(new_kpk)
    open(out_exe, 'wb').write(patch_exe_directory(open(exe, 'rb').read(), patches))
    sys.stderr.write('wrote %s (%d) and %s\n' % (out_kpk, len(new_kpk), out_exe))
    return True


if __name__ == '__main__':
    a = sys.argv
    if len(a) < 2:
        print('usage: kpktool.py unpack|verify|replace ...'); sys.exit(1)
    if a[1] == 'unpack':
        cmd_unpack(a[2], a[3], a[4])
    elif a[1] == 'verify':
        sys.exit(0 if cmd_verify(a[2], a[3]) else 2)
    elif a[1] == 'replace':
        sys.exit(0 if cmd_replace(*a[2:8]) else 2)
    else:
        print('unknown command', a[1]); sys.exit(1)
