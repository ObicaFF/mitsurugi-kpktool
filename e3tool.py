import struct

MAGIC = b'E3'
OFF_BLOCK_START = 0x68
OFF_BLOCK_END   = 0x6c
ALIGN = 16
SHIFT_OFFS = (0x4c, 0x50, 0x6c, 0x70, 0x74, 0x78, 0x94)


def _read_block(data, start, end):
    out = []
    p = start
    last_term_end = start
    while p + 1 < end:
        j = p
        while j + 1 < end and not (data[j] == 0 and data[j + 1] == 0):
            j += 2
        if j + 1 >= end:
            break
        try:
            s = data[p:j].decode('utf-16le')
        except UnicodeDecodeError:
            break
        out.append(s)
        p = j + 2
        last_term_end = p
        if all(b == 0 for b in data[p:end]):
            break
    return out, end - last_term_end


def _pack_block(strings, pad_len):
    out = bytearray()
    for s in strings:
        out += s.encode('utf-16le')
        out += b'\x00\x00'
    out += b'\x00' * pad_len
    return bytes(out)


def parse(data):
    if len(data) < 0x98 or data[:2] != MAGIC:
        raise ValueError("not an .e3 file")
    n = len(data)
    bs = struct.unpack_from('<I', data, OFF_BLOCK_START)[0]
    be = struct.unpack_from('<I', data, OFF_BLOCK_END)[0]
    has_block = 0 < bs < be <= n
    if has_block:
        strings, pad_len = _read_block(data, bs, be)
    else:
        strings, pad_len = [], 0
    return {
        'version': struct.unpack_from('<H', data, 2)[0],
        'orig_len': n,
        'block_start': bs,
        'block_end': be,
        'has_block': has_block,
        'strings': strings,
        'pad_len': pad_len,
        'prefix': bytes(data[:bs]) if has_block else bytes(data),
        'suffix': bytes(data[be:]) if has_block else b'',
        '_raw': bytes(data),
    }


def build(model):
    if not model['has_block']:
        return model['_raw']
    bs = model['block_start']
    old_len = model['block_end'] - bs
    core = sum(len(s.encode('utf-16le')) + 2 for s in model['strings'])
    pad_len = (-core) % ALIGN if model.get('_dirty') else model['pad_len']
    block = _pack_block(model['strings'], pad_len)
    delta = len(block) - old_len
    prefix = bytearray(model['prefix'])
    if delta != 0:
        for off in SHIFT_OFFS:
            v = struct.unpack_from('<I', prefix, off)[0]
            if v >= model['block_end']:
                struct.pack_into('<I', prefix, off, v + delta)
    return bytes(prefix) + block + model['suffix']


def set_strings(model, new_strings):
    if not model['has_block']:
        if new_strings:
            raise ValueError("no string block to edit")
        return
    if len(new_strings) != len(model['strings']):
        raise ValueError("string count must match (%d expected, got %d)"
                         % (len(model['strings']), len(new_strings)))
    model['strings'] = list(new_strings)
    model['_dirty'] = True
