import struct

HEADER_SIZE = 0x90
TABLE_OFF   = 0x30
TABLE_N     = 24
STR_ENTRY   = 12
END_ENTRY   = 13
ALIGN       = 16


def _read_block(data, start):
    n = len(data)
    strs = []
    p = start
    while p + 1 < n:
        if data[p] == 0 and data[p + 1] == 0:
            break
        j = p
        while j + 1 < n and not (data[j] == 0 and data[j + 1] == 0):
            j += 2
        try:
            s = data[p:j].decode('utf-16le')
        except UnicodeDecodeError:
            break
        strs.append(s)
        p = j + 2
    return strs, p


def _pack_block(strings):
    out = bytearray()
    for s in strings:
        out += s.encode('utf-16le')
        out += b'\x00\x00'
    while len(out) % ALIGN != 0:
        out += b'\x00'
    return bytes(out)


def parse(data):
    if len(data) < HEADER_SIZE:
        raise ValueError("too short")
    typ = struct.unpack_from('<I', data, 0)[0]
    if typ != 4:
        raise ValueError("not a type-0x04 file (type=0x%x)" % typ)
    table = list(struct.unpack_from('<%dI' % TABLE_N, data, TABLE_OFF))
    str_start = table[STR_ENTRY]
    str_end   = table[END_ENTRY]
    if str_start == 0 or str_start >= len(data):
        strings, content_end = [], str_start
    else:
        strings, content_end = _read_block(data, str_start)
    return {
        'type': typ,
        'name_md5': data[4:20],
        'header_u16': list(struct.unpack_from('<12H', data, 0x14)),
        'table': table,
        'str_start': str_start,
        'str_end': str_end,
        'strings': strings,
        'prefix': bytes(data[:str_start]),
        'suffix': bytes(data[str_end:]),
        'block_raw': bytes(data[str_start:str_end]),
        'orig_len': len(data),
    }


def build(model):
    table = list(model['table'])
    str_start = model['str_start']
    if str_start == 0 or str_start >= model['orig_len']:
        block = b''
        new_block_len = old_block_len = 0
    else:
        block = _pack_block(model['strings'])
        new_block_len = len(block)
        old_block_len = model['str_end'] - str_start
    delta = new_block_len - old_block_len
    new_table = list(table)
    for i in range(13, 22):
        if new_table[i] >= str_start:
            new_table[i] += delta
    prefix = bytearray(model['prefix'])
    struct.pack_into('<%dI' % TABLE_N, prefix, TABLE_OFF, *new_table)
    out = bytes(prefix) + block + model['suffix']
    if len(out) % ALIGN != 0:
        out += b'\x00' * (ALIGN - len(out) % ALIGN)
    return out


def set_strings(model, new_strings):
    if model['str_start'] == 0 or model['str_start'] >= model['orig_len']:
        if new_strings:
            raise ValueError("no dialogue block to edit")
        return
    if len(new_strings) != len(model['strings']):
        raise ValueError("string count must match (%d expected, got %d)"
                         % (len(model['strings']), len(new_strings)))
    model['strings'] = list(new_strings)
